# scraper_engine/sources/ratchakitcha.py
from scraper_engine.base_client import BaseClient

class Source:
    async def fetch(self, client: BaseClient):
        page = await client.new_page()
        await page.goto("https://ratchakitcha.soc.go.th/")
        await page.wait_for_timeout(2000)
        html = await page.content()  # пригодится позже для парсинга
        # Пока возвращаем только URL и статус
        #return [{"url": page.url, "status": "ok"}]
        return [{
            "url": page.url,
            "status": "ok",
            "html": html,
        }]
