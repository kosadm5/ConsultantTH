import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from scraper_engine.base_client import BaseClient

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
TEST_URLS_FILE = OUTPUT_DIR / "ocs_law_test_urls.txt"


class Source:
    """
    Простой разведчик: берёт список полных URL законов из файла
    /data/raw/ocs_law_test_urls.txt и для каждого:
      - открывает страницу;
      - сохраняет HTML;
      - логирует все timeline-* версии и наличие TH/EN кнопок;
      - пробует скачать TH/EN PDF.
    """

    name = "ocs_laws_deep_manual"

    async def _load_urls(self):
        if not TEST_URLS_FILE.exists():
            print("NO TEST URL FILE:", TEST_URLS_FILE)
            return []
        urls = []
        for line in TEST_URLS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
        print("LOADED", len(urls), "TEST URLS")
        return urls

    async def _open_law_page(self, page, url: str):
        print("\nOPEN LAW PAGE:", url)
        try:
            await page.goto(url, timeout=60000)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)
        except PlaywrightTimeoutError:
            print("  WARN: timeout opening law page")
        except Exception as e:
            print("  ERROR: cannot open law page:", e)

    async def _download_pdf(self, page, click_selector: str, out_path: Path) -> bool:
        try:
            async with page.expect_download() as dp:
                await page.click(click_selector)
            download = await dp.value
            await download.save_as(str(out_path))
            print("    PDF SAVED:", out_path.name)
            return True
        except Exception as e:
            print("    WARN: download failed for", click_selector, "|", e)
            return False

    async def fetch(self, client: BaseClient):
        page = await client.new_page()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        urls = await self._load_urls()
        results = []

        for idx, url in enumerate(urls):
            await self._open_law_page(page, url)

            # сохраняем HTML страницы
            try:
                html = await page.content()
                html_fn = OUTPUT_DIR / f"ocs_law_manual_{idx}.html"
                html_fn.write_text(html, encoding="utf-8")

                html_meta = {
                    "url": page.url,
                    "input_url": url,
                    "filename": f"/app/data/raw/ocs_law_manual_{idx}.html",
                    "fetched_at": datetime.utcnow().isoformat() + "Z",
                    "source": "ocs",
                    "type": "law_html",
                    "idx": idx,
                }
                (OUTPUT_DIR / f"ocs_law_manual_{idx}.html.meta.json").write_text(
                    json.dumps(html_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print("  HTML SAVED:", html_fn.name)
            except Exception as e:
                print("  ERROR: cannot save html:", e)

            versions = []
            try:
                timelines = await page.query_selector_all("div[id^='timeline-']")
                print("  TIMELINE BLOCKS:", len(timelines))

                for i, tl in enumerate(timelines):
                    label_el = await tl.query_selector(".version-label, span")
                    label = (await label_el.inner_text() or "").strip() if label_el else ""

                    th_btn = await tl.query_selector("button:not([disabled])")
                    has_th = th_btn is not None

                    en_selector = f"button#translation-{i}"
                    en_btn = await page.query_selector(en_selector)
                    has_en = en_btn is not None

                    print(f"  VERSION {i}: label={label} | TH={has_th} EN={has_en}")

                    rec = {
                        "index": i,
                        "label": label,
                        "has_th": has_th,
                        "has_en": has_en,
                        "th_pdf": None,
                        "en_pdf": None,
                    }

                    if has_th:
                        th_out = OUTPUT_DIR / f"ocs_law_manual_{idx}_v{i}_TH.pdf"
                        ok = await self._download_pdf(
                            page,
                            f"div[id='timeline-{i}'] button:not([disabled])",
                            th_out,
                        )
                        if ok:
                            rec["th_pdf"] = str(th_out)

                    if has_en:
                        en_out = OUTPUT_DIR / f"ocs_law_manual_{idx}_v{i}_EN.pdf"
                        ok = await self._download_pdf(page, en_selector, en_out)
                        if ok:
                            rec["en_pdf"] = str(en_out)

                    versions.append(rec)
            except Exception as e:
                print("  ERROR: timeline parsing failed:", e)

            results.append({"url": url, "versions": versions})

        summary = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "items": results,
        }
        (OUTPUT_DIR / "ocs_laws_deep_manual_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        await page.close()
        print("\nLAWS DEEP MANUAL RETURNED", len(results), "items")
        return results


async def main():
    client = BaseClient()
    try:
        src = Source()
        items = await src.fetch(client)
        print("LAWS DEEP MANUAL RETURNED", len(items), "items")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
