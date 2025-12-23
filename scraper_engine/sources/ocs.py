import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

from scraper_engine.base_client import BaseClient
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th"
MAX_ITEMS = int(os.getenv("OCS_MAX_ITEMS", "100"))  # сколько карточек обрабатывать за раз


async def wait_spinner(page, timeout: int = 15000):
    """
    Дождаться исчезновения оверлея ngx-spinner, чтобы клики не упирались
    в перекрывающий div.
    """
    try:
        await page.wait_for_selector(
            "div.ngx-spinner-overlay.ng-tns-c32-1",
            state="detached",
            timeout=timeout,
        )
    except PlaywrightTimeoutError:
        print("Spinner still visible, continue anyway")


class OCSSource:
    BASE = BASE

    async def _open_constitution_list(self, page):
        """Навигация в раздел конституций на уже созданной странице."""
        try:
            await page.goto(self.BASE, timeout=60000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

            # верхнее меню: "กฎหมาย" -> "รัฐธรรมนูญ"
            await page.get_by_text("กฎหมาย").nth(0).click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(2000)

            await page.get_by_text("รัฐธรรมนูญ").nth(0).click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(5000)
        except PlaywrightTimeoutError:
            print("Timeout loading constitution list")

    async def fetch_constitution_list(self, client: BaseClient):
        """Получить страницу списка конституций и сохранить HTML списка."""
        page = await client.new_page()
        await self._open_constitution_list(page)

        html = await page.content()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        fn = OUTPUT_DIR / "ocs_constitution_list.html"
        fn.write_text(html, encoding="utf-8")

        meta = {
            "url": f"{self.BASE} (constitution list)",
            "filename": "/app/data/raw/ocs_constitution_list.html",
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "ocs",
            "type": "constitution_list",
        }
        (OUTPUT_DIR / "ocs_constitution_list.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

        return page

    async def fetch_constitution_2017_html(self, client: BaseClient):
        """
        Отдельный проход: на новой странице находим карточку 2017 года
        (6/4/2560), кликаем по заголовку, сохраняем HTML-представление.
        """
        page = await client.new_page()
        await self._open_constitution_list(page)
        await wait_spinner(page)

        cards = await page.query_selector_all("app-item-search-result")
        print("2017 PASS | RESULT CARDS:", len(cards))

        for card in cards:
            # читаем дату и теги
            date_th = None
            date_en = None
            date_spans = await card.query_selector_all(
                "div.ms-3 span.ng-star-inserted"
            )
            if len(date_spans) >= 1:
                date_th = (await date_spans[0].inner_text() or "").strip()
            if len(date_spans) >= 2:
                date_en = (await date_spans[1].inner_text() or "").strip()

            if date_th != "6/4/2560":
                continue

            title_el = await card.query_selector("span.pointer b")
            title = (await title_el.inner_text() or "").strip() if title_el else ""

            tags: list[str] = []
            tag_elems = await card.query_selector_all("p-tag span.p-tag")
            for te in tag_elems:
                ttxt = (await te.inner_text() or "").strip()
                if ttxt:
                    tags.append(ttxt)

            print("Found 2017 constitution card, saving HTML view")

            title_link = await card.query_selector("span.pointer")
            if title_link:
                await wait_spinner(page)
                async with page.expect_navigation():
                    await title_link.click()
                await wait_spinner(page)

                html = await page.content()
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                html_fn = OUTPUT_DIR / "ocs_constitution_2017.html"
                html_fn.write_text(html, encoding="utf-8")

                meta_2017 = {
                    "url": page.url,
                    "filename": "/app/data/raw/ocs_constitution_2017.html",
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "source": "ocs",
                    "type": "constitution_2017_html_view",
                    "title": title,
                    "date_th": date_th,
                    "date_en": date_en,
                    "tags": tags,
                }
                (OUTPUT_DIR / "ocs_constitution_2017.meta.json").write_text(
                    json.dumps(meta_2017, ensure_ascii=False),
                    encoding="utf-8",
                )

            break  # достаточно одного раза

        await page.close()

    async def fetch_constitution_pdfs(self, client: BaseClient, max_items: int | None = None):
        """
        Основной проход по PDF: работает на свежей странице списка и не
        выполняет навигаций внутрь карточек, чтобы не ломать handle'ы.
        """
        if max_items is None:
            max_items = MAX_ITEMS

        page = await client.new_page()
        await self._open_constitution_list(page)
        await wait_spinner(page)

        saved = 0
        page_idx = 0

        while saved < max_items:
            cards = await page.query_selector_all("app-item-search-result")
            print(f"PAGE {page_idx} | RESULT CARDS:", len(cards))

            if not cards:
                break

            for idx in range(len(cards)):
                if saved >= max_items:
                    break

                try:
                    # каждый раз берём актуальный card, чтобы избежать оторванных handle'ов
                    cards = await page.query_selector_all("app-item-search-result")
                    if idx >= len(cards):
                        break
                    card = cards[idx]

                    title_el = await card.query_selector("span.pointer b")
                    title = (await title_el.inner_text() or "").strip() if title_el else ""
                    if not title:
                        title = (await card.inner_text() or "").strip().split("\n")[0]
                    if not title:
                        continue

                    date_th = None
                    date_en = None
                    date_spans = await card.query_selector_all(
                        "div.ms-3 span.ng-star-inserted"
                    )
                    if len(date_spans) >= 1:
                        date_th = (await date_spans[0].inner_text() or "").strip()
                    if len(date_spans) >= 2:
                        date_en = (await date_spans[1].inner_text() or "").strip()

                    tags: list[str] = []
                    tag_elems = await card.query_selector_all("p-tag span.p-tag")
                    for te in tag_elems:
                        ttxt = (await te.inner_text() or "").strip()
                        if ttxt:
                            tags.append(ttxt)

                    global_idx = page_idx * len(cards) + idx
                    print(f"Card {global_idx} TITLE: {title} | date_th={date_th} | tags={tags}")

                    # 2017 год здесь пропускаем: он уже обработан отдельно как HTML
                    if date_th == "6/4/2560":
                        print("Skip 2017 card in PDF pass")
                        continue

                    pdf_icon = await card.query_selector("i.fa-file-pdf")
                    if not pdf_icon:
                        print("No PDF icon for card", global_idx)
                        continue

                    await wait_spinner(page)
                    async with page.expect_download(timeout=45000) as dl_info:
                        await pdf_icon.click()
                    download = await dl_info.value
                    await wait_spinner(page)

                    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                    pdf_fn = OUTPUT_DIR / f"ocs_constitution_{saved + 1}.pdf"
                    await download.save_as(pdf_fn)

                    pdf_url = download.url
                    print("Downloaded PDF:", pdf_fn, "from", pdf_url)

                    meta = {
                        "url": pdf_url or self.BASE,
                        "filename": f"/app/data/raw/ocs_constitution_{saved + 1}.pdf",
                        "fetched_at": datetime.utcnow().isoformat() + "Z",
                        "source": "ocs",
                        "type": "constitution_pdf",
                        "title": title,
                        "date_th": date_th,
                        "date_en": date_en,
                        "tags": tags,
                    }
                    (OUTPUT_DIR / f"ocs_constitution_{saved + 1}.meta.json").write_text(
                        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
                    )

                    saved += 1

                except Exception as e:
                    print("Error on card", idx, e)
                    continue

            if saved >= max_items:
                break

            next_btn = await page.query_selector("button.p-paginator-next:not(.p-disabled)")
            if not next_btn:
                print("No more pages in paginator")
                break

            await wait_spinner(page)
            await next_btn.click()
            await page.wait_for_load_state("networkidle")
            await wait_spinner(page)

            page_idx += 1

        print("TOTAL DOWNLOADED PDF:", saved)
        await page.close()

    async def run(self):
        client = BaseClient()
        try:
            # сначала отдельный проход для 2017 HTML
            await self.fetch_constitution_2017_html(client)
            # затем основной проход по всем PDF
            await self.fetch_constitution_pdfs(client, max_items=MAX_ITEMS)
        finally:
            await client.close()


async def main():
    src = OCSSource()
    await src.run()


if __name__ == "__main__":
    asyncio.run(main())
