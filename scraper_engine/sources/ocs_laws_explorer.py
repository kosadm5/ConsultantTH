import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

from scraper_engine.base_client import BaseClient

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th/council-of-state/"
MAX_ITEMS = int(os.getenv("OCS_LAWS_MAX_ITEMS", "100000"))


async def handle_cookie_banner(page):
    """Checks for and closes the cookie banner if it appears."""
    try:
        cookie_banner_locator = page.locator("app-public-cookie")
        # Use a short timeout to prevent blocking if the banner isn't there.
        if await cookie_banner_locator.is_visible(timeout=500):
            print("Cookie banner detected. Attempting to close it.")
            # The close button seems to be standard in p-dialog
            close_button = cookie_banner_locator.locator("button.p-dialog-header-close")
            if await close_button.is_visible():
                await close_button.click()
                print("Clicked the cookie banner close button.")
                # Wait a moment for the banner to disappear
                await page.wait_for_timeout(1000)
            else:
                print("Cookie banner close button not found.")
    except Exception:
        # If the banner handling fails, log it but don't crash the scraper.
        print("Info: Could not handle cookie banner. Continuing anyway.")


class Source:
    """Исследователь ВСЕХ законов с главной страницы."""

    name = "ocs_laws_explorer"

    async def fetch(self, client: BaseClient):
        page = await client.new_page()

        # 1. Переход на главную страницу
        await page.goto(BASE, timeout=60000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000) # Увеличено ожидание для полной загрузки SPA

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        list_html = await page.content()
        (OUTPUT_DIR / "ocs_laws_explore_list.html").write_text(
            list_html,
            encoding="utf-8",
        )

        all_items = []
        saved = 0
        page_idx = 0

        while saved < MAX_ITEMS:
            # Handle potential pop-ups at the start of each page iteration
            await handle_cookie_banner(page)
            
            cards = await page.query_selector_all("app-item-search-result")
            print(f"LAWS PAGE {page_idx} | RESULT CARDS:", len(cards))
            if not cards:
                break

            for idx in range(len(cards)):
                if saved >= MAX_ITEMS:
                    break
                
                # Re-check for banner before interacting with a specific card.
                await handle_cookie_banner(page)

                cards = await page.query_selector_all("app-item-search-result")
                if idx >= len(cards):
                    break

                card = cards[idx]

                # заголовок
                title_el = await card.query_selector("span.pointer b")
                title = (await title_el.inner_text() or "").strip() if title_el else ""
                if not title:
                    title = (await card.inner_text() or "").strip().split("\n")[0]

                # стабильный URL карточки закона (#/public/doc/...)
                law_page_url = None
                full_url = None

                # сначала пробуем ссылку внутри карточки
                link_el = await card.query_selector("a[href*='#/public/doc/']")
                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        if href.startswith("http"):
                            full_url = href
                        else:
                            full_url = f"{BASE}{href}"
                        law_page_url = href

                # даты
                date_th = None
                date_en = None
                date_spans = await card.query_selector_all(
                    "div.ms-3 span.ng-star-inserted"
                )
                if len(date_spans) >= 1:
                    date_th = (await date_spans[0].inner_text() or "").strip()
                if len(date_spans) >= 2:
                    date_en = (await date_spans[1].inner_text() or "").strip()

                # теги
                tags = []
                tag_elems = await card.query_selector_all("p-tag span.p-tag")
                for te in tag_elems:
                    ttxt = (await te.inner_text() or "").strip()
                    if ttxt:
                        tags.append(ttxt)

                # иконка PDF
                pdf_icon = await card.query_selector("i.fa-file-pdf")
                has_pdf = pdf_icon is not None
                pdf_url = None
                saved_pdf = None

                if pdf_icon:
                    try:
                        # Increased timeout for download, shorter for the click action
                        async with page.expect_download(timeout=60000) as dl_info:
                            await pdf_icon.click(timeout=15000)
                        
                        download = await dl_info.value
                        pdf_url = download.url
                        pdf_path = OUTPUT_DIR / f"ocs_law_{saved + 1}.pdf"
                        await download.save_as(pdf_path)
                        saved_pdf = f"/app/data/raw/ocs_law_{saved + 1}.pdf"

                        meta = {
                            "url": pdf_url or BASE,
                            "filename": saved_pdf,
                            "fetched_at": datetime.utcnow().isoformat() + "Z",
                            "source": "ocs",
                            "type": "law_pdf",
                            "title": title,
                            "date_th": date_th,
                            "date_en": date_en,
                            "tags": tags,
                            "base_url": BASE,
                            "law_page_url": law_page_url,
                            "full_url": full_url,
                        }
                        (OUTPUT_DIR / f"ocs_law_{saved + 1}.meta.json").write_text(
                            json.dumps(meta, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        saved += 1
                    except Exception as e:
                        print(f"Error during laws PDF download for card {idx}: {e}")


                all_items.append(
                    {
                        "page_idx": page_idx,
                        "idx_on_page": idx,
                        "title": title,
                        "date_th": date_th,
                        "date_en": date_en,
                        "tags": tags,
                        "has_pdf": has_pdf,
                        "pdf_url": pdf_url,
                        "saved_pdf": saved_pdf,
                        "law_page_url": law_page_url,
                        "full_url": full_url,
                    }
                )

                if saved >= MAX_ITEMS:
                    break

            # --- СУПЕР УМНАЯ ПАГИНАЦИЯ 10.0 (С ожиданием контента) ---
            try:
                page_idx_ui = page_idx + 1
                print(f"Attempting to navigate from page {page_idx_ui}...")
                
                clicked = False

                # --- Стратегия 1: Клик по одиночной стрелке 'Next' (p-paginator-next) ---
                next_arrow_locator = page.locator("button.p-paginator-next")
                if await next_arrow_locator.count() > 0:
                    is_arrow_disabled = "p-disabled" in (await next_arrow_locator.get_attribute("class") or "")
                    if not is_arrow_disabled:
                        print(f"Next arrow is active. Clicking it.")
                        await next_arrow_locator.evaluate("el => el.click()")
                        clicked = True
                    else:
                        print(f"Next arrow is disabled on page {page_idx_ui}. Assuming end of list.")
                        break # Если стрелка неактивна, это конец.
                else:
                    print(f"Next arrow locator not found on page {page_idx_ui}. Assuming end of list.")
                    break # Если стрелки нет, это конец.

                if not clicked:
                    break

                # --- ШАГ 2: Явное ожидание загрузки контента новой страницы ---
                try:
                    print("Waiting for new page content to load...")
                    # Ждем, пока первая карточка на новой странице не станет видимой
                    await page.locator("app-item-search-result").first.wait_for(state="visible", timeout=30000)
                    print("New page content loaded successfully.")
                    # Дополнительная короткая пауза для стабилизации UI
                    await page.wait_for_timeout(1500)
                except Exception as e:
                    print(f"CRITICAL: Timed out or failed while waiting for next page's content. Error: {e}")
                    screenshot_path = OUTPUT_DIR / f"critical_content_wait_failed_on_page_{page_idx_ui}.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    print(f"Screenshot saved to {screenshot_path}. Breaking loop.")
                    break

                # --- ШАГ 3: Надежная проверка смены страницы ---
                try:
                    current_page_number_locator = page.locator("button.p-paginator-page.p-highlight")
                    # Явно ждем появления подсвеченной кнопки
                    await current_page_number_locator.wait_for(state="visible", timeout=10000)
                    
                    current_page_text = await current_page_number_locator.inner_text()
                    current_page_from_ui = int(current_page_text)

                    if current_page_from_ui == page_idx_ui:
                        print(f"ERROR: Page did not advance from {page_idx_ui}. Stuck in loop. Breaking.")
                        break

                    page_idx = current_page_from_ui - 1 # Корректировка на 0-базовую индексацию
                    print(f"Successfully advanced to page {current_page_from_ui}.")

                except Exception as e:
                    print(f"CRITICAL: Could not verify page advancement after loading content. Error: {e}")
                    screenshot_path = OUTPUT_DIR / f"critical_verify_failed_on_page_{page_idx_ui}.png"
                    await page.screenshot(path=screenshot_path, full_page=True)
                    print(f"Screenshot saved to {screenshot_path}. Breaking loop.")
                    break

            except Exception as e:
                print(f"Critical error during smart pagination on page {page_idx_ui}. Error: {e}")
                screenshot_path = OUTPUT_DIR / f"critical_error_on_page_{page_idx_ui}.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"Screenshot saved to {screenshot_path}")
                break
            # --- КОНЕЦ СУПЕР УМНОЙ ПАГИНАЦИИ 10.0 ---

            # --- Периодическая очистка и пауза ---
            if page_idx > 0 and page_idx % 25 == 0:  # Каждые 25 страниц
                try:
                    import gc
                    print(f"--- Выполнение периодической очистки на странице {page_idx}. Принудительный вызов сборщика мусора. ---")
                    gc.collect()
                    print("--- Небольшая пауза (15 секунд) для снижения нагрузки на сервер. ---")
                    await page.wait_for_timeout(15000)
                except Exception as e:
                    print(f"Предупреждение: Не удалось выполнить шаг очистки: {e}")

        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "base_url": BASE,
            "section": "all_laws",
            "items": all_items,
        }
        (OUTPUT_DIR / "ocs_laws_explore_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        await page.close()
        print("LAWS EXPLORER RETURNED", len(all_items), "items")
        return all_items


async def main():
    client = BaseClient()
    try:
        src = Source()
        items = await src.fetch(client)
        print("LAWS EXPLORER RETURNED", len(items), "items")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
