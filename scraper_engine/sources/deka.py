# scraper_engine/sources/deka.py

from scraper_engine.base_client import BaseClient
from pathlib import Path
import json, os

class Source:
    name = "deka"

    async def fetch(self, client: BaseClient):
        page = await client.new_page()
        await page.goto("https://deka.supremecourt.or.th/")
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)

        # селектор под список решений нужно будет подобрать по реальной разметке
        links = await page.query_selector_all("a[href*='judgement']")
        links = links[:3]

        out_dir = Path(os.getenv("OUTPUT_DIR", "/data/raw"))
        out_dir.mkdir(parents=True, exist_ok=True)

        items = []
        for i, link in enumerate(links):
            url = await link.get_attribute("href")
            if not url:
                continue
            if url.startswith("/"):
                url = "https://deka.supremecourt.or.th" + url

            doc_page = await client.new_page()
            await doc_page.goto(url)
            await doc_page.wait_for_load_state("networkidle")
            html = await doc_page.content()

            fn = out_dir / f"deka_case_{i}.html"
            fn.write_text(html, encoding="utf-8")

            meta = {
                "url": url,
                "filename": str(fn),
                "fetched_at": "2025-11-29T00:00:00Z",
                "source": "deka",
            }
            meta_fn = out_dir / f"deka_case_{i}.meta.json"
            meta_fn.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

            items.append({"url": url, "file": str(fn), "meta": str(meta_fn)})

        return items
