import asyncio
import os
import json
from pathlib import Path
from datetime import datetime

from scraper_engine.base_client import BaseClient

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
BASE = "https://searchlaw.ocs.go.th"


class Source:
    """Исследователь структуры раздела конституций на searchlaw.ocs.go.th"""

    name = "ocs_explorer"

    async def fetch(self, client: BaseClient):
        page = await client.new_page()

        # 1. Переходим на сайт и в раздел Конституций
        await page.goto(BASE, timeout=60000)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)

        # верхнее меню: "กฎหมาย" -> "รัฐธรรมนูญ"
        await page.get_by_text("กฎหมาย").nth(0).click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)

        await page.get_by_text("รัฐธรรมนูญ").nth(0).click()
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # сохраним HTML страницы списка как есть
        list_html = await page.content()
        (OUTPUT_DIR / "ocs_explore_constitution_list.html").write_text(
            list_html, encoding="utf-8"
        )

        # 2. Собираем выбранные годы из мультиселекта
        years = []
        year_tokens = await page.query_selector_all(
            ".year-multiselect span.p-multiselect-token-label"
        )
        for t in year_tokens:
            txt = (await t.inner_text() or "").strip()
            if txt:
                years.append(txt)

        # 3. Карточки результатов (правая колонка)
        cards = await page.query_selector_all("app-item-search-result")
        print("TOTAL RESULT CARDS:", len(cards))

        items = []
        for idx, card in enumerate(cards):
            # ограничимся, скажем, 15 первыми для разведки
            if idx >= 15:
                break

            # заголовок
            title = None
            title_el = await card.query_selector("span.pointer b")
            if title_el:
                title = (await title_el.inner_text() or "").strip()
            if not title:
                # fallback: весь текст карточки
                title = (await card.inner_text() or "").strip().split("\n")[0]

            # даты (тайская + григорианская)
            date_th = None
            date_en = None
            date_spans = await card.query_selector_all(
                "div.ms-3 span.ng-star-inserted"
            )
            if len(date_spans) >= 1:
                date_th = (await date_spans[0].inner_text() or "").strip()
            if len(date_spans) >= 2:
                date_en = (await date_spans[1].inner_text() or "").strip()

            # теги (p-tag)
            tags = []
            tag_elems = await card.query_selector_all("p-tag span.p-tag")
            for te in tag_elems:
                ttxt = (await te.inner_text() or "").strip()
                if ttxt:
                    tags.append(ttxt)

            # наличие PDF-иконки и попытка поймать URL
            pdf_icon = await card.query_selector("i.fa-file-pdf")
            has_pdf = pdf_icon is not None
            pdf_url = None
            saved_pdf = None

            if pdf_icon and idx < 3:
                # только для первых 3 попробуем реально скачать, чтобы понять механику
                try:
                    async with page.expect_download() as dl_info:
                        await pdf_icon.click()
                    download = await dl_info.value
                    pdf_url = download.url

                    pdf_path = OUTPUT_DIR / f"ocs_explore_sample_{idx + 1}.pdf"
                    await download.save_as(pdf_path)
                    saved_pdf = str(pdf_path)
                    print("Downloaded sample PDF:", pdf_path)
                except Exception as e:
                    print("Error during PDF download for card", idx, e)

            item = {
                "idx": idx,
                "title": title,
                "date_th": date_th,
                "date_en": date_en,
                "tags": tags,
                "has_pdf": has_pdf,
                "pdf_url": pdf_url,
                "saved_pdf": saved_pdf,
            }
            items.append(item)

        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "base_url": BASE,
            "years_selected": years,
            "items": items,
        }

        (OUTPUT_DIR / "ocs_explore_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # возвращаем для отладки через runner.py
        return items


async def main():
    client = BaseClient()
    try:
        src = Source()
        items = await src.fetch(client)
        print("EXPLORER RETURNED", len(items), "items")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
