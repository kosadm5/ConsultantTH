import asyncio
import os
import json
import argparse
from pathlib import Path
from datetime import datetime

from scraper_engine.base_client import BaseClient

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th/council-of-state/"
MAX_ITEMS = int(os.getenv("OCS_LAWS_MAX_ITEMS", "100000"))


async def handle_cookie_banner(page):
    """
    Checks for and closes the cookie banner if it appears.
    This version is more robust, trying multiple strategies to close the banner.
    """
    try:
        # Increased timeout to ensure we catch lazily-loaded banners.
        banner_locator = page.locator("app-public-cookie")
        await banner_locator.wait_for(state="visible", timeout=3000)
        print("Cookie banner detected. Attempting to close it.")

        # Strategy 1: Find the 'Accept' button by its likely text ("ยอมรับ"). This is the most reliable.
        accept_button_text = banner_locator.get_by_role('button', name='ยอมรับ')
        if await accept_button_text.is_visible():
            print("Found cookie banner 'Accept' button by text. Clicking it.")
            await accept_button_text.click()
            await page.wait_for_timeout(1000)  # Wait for dismissal animation
            return

        # Strategy 2: Find by a common PrimeNG accept button class.
        accept_button_class = banner_locator.locator("button.p-confirm-dialog-accept")
        if await accept_button_class.is_visible():
            print("Found cookie banner 'Accept' button by class. Clicking it.")
            await accept_button_class.click()
            await page.wait_for_timeout(1000)
            return

        # Strategy 3: Fallback to the generic close icon button.
        close_button = banner_locator.locator("button.p-dialog-header-close")
        if await close_button.is_visible():
            print("Found cookie banner 'Close' button. Clicking it.")
            await close_button.click()
            await page.wait_for_timeout(1000)
            return

        print("Cookie banner was detected, but no known close/accept button was found.")

    except Exception:
        # This can happen if the banner doesn't appear (timeout) or if clicking fails.
        # It's safe to ignore and continue.
        # print("Info: No cookie banner found or failed to close it. Continuing.")
        pass


class Source:
    """Исследователь ВСЕХ законов с главной страницы."""

    name = "ocs_laws_explorer"

    async def fetch(self, client: BaseClient, start_page: int = 1, max_pages: int = 10000):
        page = await client.new_page()

        # 1. Переход на главную страницу
        await page.goto(BASE, timeout=60000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000) # Увеличено ожидание для полной загрузки SPA
        await handle_cookie_banner(page)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # --- Переход к начальной странице ---
        page_idx = start_page - 1
        if page_idx > 0:
            print(f"--- Navigating to start page: {start_page} ---")
            # Кликаем на "Next" page_idx раз, чтобы добраться до нужной страницы
            for i in range(page_idx):
                try:
                    ui_page = i + 1
                    print(f"Navigating from {ui_page} to {ui_page + 1}...")
                    next_arrow_locator = page.locator("button.p-paginator-next:not(.p-disabled)")
                    await next_arrow_locator.click(timeout=30000)
                    # Ждем, пока номер страницы обновится
                    await page.locator(f"button.p-paginator-page.p-highlight:text-is('{ui_page + 1}')").wait_for(timeout=30000)
                except Exception as e:
                    print(f"FATAL: Could not navigate to start page {start_page}. Failed at step {i}. Error: {e}")
                    await page.screenshot(path=OUTPUT_DIR / f"fatal_start_page_nav_error.png", full_page=True)
                    return []
            print(f"--- Successfully navigated to start page {start_page}. Starting scrape. ---")


        all_items = []
        saved = 0
        pages_processed = 0

        while pages_processed < max_pages:
            # Handle potential pop-ups at the start of each page iteration
            await handle_cookie_banner(page)
            
            cards = await page.query_selector_all("app-item-search-result")
            current_ui_page = page_idx + 1
            print(f"LAWS PAGE {current_ui_page} | RESULT CARDS:", len(cards))
            if not cards:
                print(f"No cards found on page {current_ui_page}. Assuming end of list.")
                break

            for idx in range(len(cards)):
                if saved >= MAX_ITEMS:
                    break
                
                await handle_cookie_banner(page)

                cards = await page.query_selector_all("app-item-search-result")
                if idx >= len(cards):
                    break

                card = cards[idx]

                title_el = await card.query_selector("span.pointer b")
                title = (await title_el.inner_text() or "").strip() if title_el else ""
                if not title:
                    title = (await card.inner_text() or "").strip().split("\n")[0]

                law_page_url = None
                full_url = None
                link_el = await card.query_selector("a[href*='#/public/doc/']")
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        full_url = f"{BASE}{href}" if not href.startswith("http") else href
                        law_page_url = href

                date_th, date_en = None, None
                date_spans = await card.query_selector_all("div.ms-3 span.ng-star-inserted")
                if len(date_spans) >= 1: date_th = (await date_spans[0].inner_text() or "").strip()
                if len(date_spans) >= 2: date_en = (await date_spans[1].inner_text() or "").strip()

                tags = [
                    (await te.inner_text() or "").strip()
                    for te in await card.query_selector_all("p-tag span.p-tag")
                ]
                tags = [t for t in tags if t]

                pdf_icon = await card.query_selector("i.fa-file-pdf")
                pdf_url, saved_pdf = None, None

                if pdf_icon:
                    try:
                        async with page.expect_download(timeout=60000) as dl_info:
                            print(f"Attempting to click PDF icon for card {idx} on page {current_ui_page} using JS click...")
                            await pdf_icon.evaluate("el => el.click()")

                        download = await dl_info.value
                        pdf_url = download.url
                        
                        # Use a more descriptive name based on page and index
                        safe_title = "".join(filter(str.isalnum, title[:30]))
                        pdf_name = f"law_p{current_ui_page}_i{idx}_{safe_title}.pdf"
                        pdf_path = OUTPUT_DIR / pdf_name
                        
                        await download.save_as(pdf_path)
                        saved_pdf = f"/app/data/raw/{pdf_path.name}"

                        meta = {
                            "url": pdf_url or BASE,
                            "filename": saved_pdf,
                            "fetched_at": datetime.utcnow().isoformat() + "Z",
                            "source": "ocs",
                            "type": "law_pdf",
                            "title": title, "date_th": date_th, "date_en": date_en, "tags": tags,
                            "base_url": BASE, "law_page_url": law_page_url, "full_url": full_url,
                        }
                        meta_path = OUTPUT_DIR / f"{pdf_path.stem}.meta.json"
                        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                        saved += 1
                    except Exception as e:
                        print(f"Error during laws PDF download for card {idx} on page {current_ui_page}: {e}")
                        try:
                            screenshot_path = OUTPUT_DIR / f"error_screenshot_page_{current_ui_page}_card_{idx}.png"
                            await page.screenshot(path=str(screenshot_path))
                            print(f"Saved error screenshot to {screenshot_path}")
                        except Exception as se:
                            print(f"Could not save screenshot: {se}")

                all_items.append({
                    "page_idx": page_idx, "idx_on_page": idx, "title": title, "date_th": date_th,
                    "date_en": date_en, "tags": tags, "has_pdf": pdf_icon is not None, "pdf_url": pdf_url,
                    "saved_pdf": saved_pdf, "law_page_url": law_page_url, "full_url": full_url,
                })

                if saved >= MAX_ITEMS:
                    print("Reached MAX_ITEMS limit. Stopping.")
                    break
            
            if saved >= MAX_ITEMS: break

            pages_processed += 1
            if pages_processed >= max_pages:
                print(f"Processed {pages_processed} pages, reaching 'max_pages' limit. Halting.")
                break

            # --- ПАГИНАЦИЯ ---
            try:
                next_arrow_locator = page.locator("button.p-paginator-next")
                if not await next_arrow_locator.count() or "p-disabled" in (await next_arrow_locator.get_attribute("class") or ""):
                    print(f"Next arrow is disabled or not found on page {current_ui_page}. Assuming end of list.")
                    break
                
                print(f"Navigating from page {current_ui_page}...")
                await next_arrow_locator.evaluate("el => el.click()")

                await page.locator("app-item-search-result").first.wait_for(state="visible", timeout=30000)
                
                current_page_number_locator = page.locator("button.p-paginator-page.p-highlight")
                await current_page_number_locator.wait_for(state="visible", timeout=10000)
                
                current_page_text = await current_page_number_locator.inner_text()
                new_ui_page = int(current_page_text)

                if new_ui_page != current_ui_page + 1:
                     print(f"ERROR: Page did not advance correctly from {current_ui_page}. New page is {new_ui_page}. Breaking.")
                     break
                
                page_idx = new_ui_page - 1
                print(f"Successfully advanced to page {new_ui_page}.")

            except Exception as e:
                print(f"Critical error during pagination on page {current_ui_page}. Error: {e}")
                screenshot_path = OUTPUT_DIR / f"critical_error_on_page_{current_ui_page}.png"
                await page.screenshot(path=str(screenshot_path), full_page=True)
                print(f"Screenshot saved to {screenshot_path}")
                break

        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "base_url": BASE, "section": "all_laws", "items": all_items,
        }
        summary_path = OUTPUT_DIR / f"summary_p{start_page}_to_p{page_idx + 1}.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        await page.close()
        print(f"LAWS EXPLORER RETURNED {len(all_items)} items across {pages_processed} pages.")
        return all_items


async def main(args):
    # Гарантируем, что начальная страница не меньше 1
    if args.start_page < 1:
        print("Warning: --start-page cannot be less than 1. Defaulting to 1.")
        args.start_page = 1
        
    client = BaseClient()
    try:
        src = Source()
        items = await src.fetch(client, start_page=args.start_page, max_pages=args.max_pages)
        print("LAWS EXPLORER RETURNED", len(items), "items")
    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape laws from OCS website.")
    parser.add_argument("--start-page", type=int, default=1, help="The page number to start scraping from (1-indexed).")
    parser.add_argument("--max-pages", type=int, default=10000, help="The maximum number of pages to scrape in this run.")
    args = parser.parse_args()
    
    asyncio.run(main(args))
