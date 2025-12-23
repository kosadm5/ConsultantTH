import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

from scraper_engine.base_client import BaseClient
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th"
MAX_ITEMS = int(os.getenv("OCS_LAWS_DEEP_MAX_ITEMS", "400"))

# сколько секунд ждать после кликов, чтобы UI точно обновился
UI_PAUSE_MS = int(os.getenv("OCS_UI_PAUSE_MS", "1200"))


async def wait_spinner(page, timeout: int = 20000):
    """Ждём, пока спиннер исчезнет (если он есть)."""
    try:
        await page.wait_for_selector("div.ngx-spinner-overlay", state="detached", timeout=timeout)
    except PlaywrightTimeoutError:
        print("WARN: spinner still visible, continue anyway")


class Source:
    """Глубокий проход по законам: заходим в карточку -> сохраняем HTML + meta (включая full_url) -> назад."""
    name = "ocs_laws_deep"

    async def _open_laws_list(self, page):
        """Открывает список законов (พระราชบัญญัติ/พระราชกำหนด)."""
        await page.goto(BASE, timeout=60000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        await page.get_by_text("กฎหมาย").first.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1000)

        await page.get_by_text("พระราชบัญญัติ/พระราชกำหนด").first.click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        await wait_spinner(page)

        # контроль: список должен появиться
        await page.wait_for_selector("app-item-search-result", timeout=30000)

    async def _ensure_list_view(self, page, reason: str):
        """Проверяет, что мы на листинге (видны карточки). Если нет — переоткрывает список."""
        try:
            await page.wait_for_selector("app-item-search-result", timeout=15000)
            return
        except Exception:
            print(f"WARN: list not visible ({reason}) -> reopening list")
            await self._open_laws_list(page)

    async def _debug_page_state(self, page, page_idx: int):
        """Диагностика состояния экрана (1 раз на страницу)."""
        cards_cnt = await page.locator("app-item-search-result").count()
        paginator_cnt = await page.locator("p-paginator").count()
        paginator_btns = await page.locator("p-paginator button").count()

        print(f"DEBUG page_idx={page_idx} url={page.url}")
        print(f"DEBUG cards_cnt={cards_cnt} paginator_cnt={paginator_cnt} paginator_buttons={paginator_btns}")

    async def _find_next_button(self, page):
        """
        Возвращает кнопку Next (следующая страница) в PrimeNG paginator.
        Не путаем с Last.
        """
        # 1) Часто есть aria-label
        btn = await page.query_selector("button[aria-label*='Next'], button[aria-label*='next']")
        if btn:
            return btn

        paginator = await page.query_selector("p-paginator")
        if not paginator:
            return None

        # 2) PrimeNG классы (самый надёжный вариант)
        btn = await paginator.query_selector("button.p-paginator-next")
        if btn:
            return btn

        # 3) Фоллбек: кнопка с иконкой "chevron-right"
        btn = await paginator.query_selector("button:has(span.pi-angle-right), button:has(span.p-paginator-icon)")
        if btn:
            return btn

        return None


    async def fetch(self, client: BaseClient):
        page = await client.new_page()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        await self._open_laws_list(page)

        processed = 0
        page_idx = 0
        all_items = []

        while processed < MAX_ITEMS:
            await self._ensure_list_view(page, reason="start of page loop")

            cards = await page.query_selector_all("app-item-search-result")
            print(f"DEEP PAGE {page_idx} | CARDS: {len(cards)}")

            await self._debug_page_state(page, page_idx)

            if not cards:
                print("DEEP: no cards found -> stop")
                break

            # обрабатываем карточки на странице
            for idx_on_page in range(len(cards)):
                if processed >= MAX_ITEMS:
                    break

                # рефреш списка, чтобы избежать stale
                cards = await page.query_selector_all("app-item-search-result")
                if idx_on_page >= len(cards):
                    print("WARN: cards count changed during loop -> break page")
                    break

                card = cards[idx_on_page]
                global_idx = processed

                # title
                title_el = await card.query_selector("span.pointer b")
                title = (await title_el.inner_text() or "").strip() if title_el else ""
                if not title:
                    title = (await card.inner_text() or "").strip().split("\n")[0]

                # dates
                date_th = None
                date_en = None
                date_spans = await card.query_selector_all("div.ms-3 span.ng-star-inserted")
                if len(date_spans) >= 1:
                    date_th = (await date_spans[0].inner_text() or "").strip()
                if len(date_spans) >= 2:
                    date_en = (await date_spans[1].inner_text() or "").strip()

                # tags
                tags = []
                tag_elems = await card.query_selector_all("p-tag span.p-tag")
                for te in tag_elems:
                    ttxt = (await te.inner_text() or "").strip()
                    if ttxt:
                        tags.append(ttxt)

                print(f"DEEP CARD {global_idx} (page={page_idx} idx={idx_on_page}) TITLE: {title} | date_th={date_th}")

                # click into doc
                title_link = await card.query_selector("span.pointer")
                if not title_link:
                    print(f"  WARN: no clickable title for card {global_idx} -> skip")
                    continue

                try:
                    async with page.expect_navigation(timeout=45000):
                        await title_link.click()
                    await page.wait_for_load_state("networkidle")
                    await wait_spinner(page)
                    await page.wait_for_timeout(UI_PAUSE_MS)
                except Exception as e:
                    print(f"  ERROR: navigation into card {global_idx} failed: {e}")
                    # пробуем вернуться в список
                    try:
                        await page.go_back(wait_until="networkidle")
                        await wait_spinner(page)
                    except Exception:
                        pass
                    await self._ensure_list_view(page, reason="after failed navigation")
                    continue

                # NOW inside doc page
                doc_url = page.url
                print(f"  DEBUG: entered doc url={doc_url}")

                # save HTML
                html = await page.content()
                html_fn = OUTPUT_DIR / f"ocs_law_full_{global_idx}.html"
                html_fn.write_text(html, encoding="utf-8")

                html_meta = {
                    "url": doc_url,
                    "full_url": doc_url,
                    "law_page_url": doc_url.replace(BASE, "") if doc_url.startswith(BASE) else doc_url,
                    "filename": f"/app/data/raw/ocs_law_full_{global_idx}.html",
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "source": "ocs",
                    "type": "law_html",
                    "law_global_idx": global_idx,
                    "title": title,
                    "date_th": date_th,
                    "date_en": date_en,
                    "tags": tags,
                }
                (OUTPUT_DIR / f"ocs_law_full_{global_idx}.html.meta.json").write_text(
                    json.dumps(html_meta, ensure_ascii=False),
                    encoding="utf-8",
                )

                # lightweight diagnostics inside doc
                versions_cnt = await page.locator("i.fa-file-pdf, canvas, svg").count()
                th_en_pdf_icons_cnt = await page.locator("i.fa-file-pdf").count()
                print(f"  DEBUG: doc versions_like={versions_cnt} pdf_icons={th_en_pdf_icons_cnt}")

                all_items.append({
                    "global_idx": global_idx,
                    "page_idx": page_idx,
                    "idx_on_page": idx_on_page,
                    "title": title,
                    "date_th": date_th,
                    "date_en": date_en,
                    "tags": tags,
                    "doc_url": doc_url,
                    "versions_like": versions_cnt,
                    "pdf_icons": th_en_pdf_icons_cnt,
                })

                # go back to list
                try:
                    await page.go_back(wait_until="networkidle")
                    await wait_spinner(page)
                    await page.wait_for_timeout(UI_PAUSE_MS)
                except Exception as e:
                    print(f"  ERROR: go_back failed for card {global_idx}: {e}")
                    await self._open_laws_list(page)

                await self._ensure_list_view(page, reason="after go_back")

                processed += 1

            if processed >= MAX_ITEMS:
                break

            # after finishing page: paginate
            await self._ensure_list_view(page, reason="before paginate")
            await page.wait_for_timeout(UI_PAUSE_MS)

            next_btn = await self._find_next_button(page)
            print(f"DEEP: next_btn_found={bool(next_btn)} (page_idx={page_idx})")

            if not next_btn:
                print(f"DEEP: STOP. next button not found at page {page_idx}")
                break

            disabled = await next_btn.get_attribute("disabled")
            classes = await next_btn.get_attribute("class")
            print(f"DEEP: next_btn disabled={disabled} classes={classes}")

            if disabled is not None or (classes and "p-disabled" in classes):
                print(f"DEEP: STOP. next button disabled at page {page_idx}")
                break

            print(f"DEEP: clicking NEXT from page {page_idx}")
            try:
                await next_btn.click()
                await page.wait_for_load_state("networkidle")
                await wait_spinner(page)
                await page.wait_for_timeout(UI_PAUSE_MS)
            except Exception as e:
                print(f"DEEP: ERROR clicking next at page {page_idx}: {e}")
                break

            page_idx += 1

        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "base_url": BASE,
            "max_items": MAX_ITEMS,
            "items_count": len(all_items),
            "items": all_items,
        }
        (OUTPUT_DIR / "ocs_laws_deep_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        await page.close()
        print(f"LAWS DEEP EXPLORER RETURNED {len(all_items)} items")
        return all_items


async def main():
    client = BaseClient()
    try:
        src = Source()
        items = await src.fetch(client)
        print(f"LAWS DEEP EXPLORER RETURNED {len(items)} items")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
