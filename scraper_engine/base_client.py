import asyncio
from scraper_engine.playwright_client import PlaywrightClient

class BaseClient:
    def __init__(self):
        self.browser = None
        self.context = None
        self.playwright = None

    async def new_page(self):
        if not self.browser:
            pw_client = PlaywrightClient()
            self.playwright, self.browser, self.context = await pw_client.start()

        return await self.context.new_page()

    async def close(self):
        if self.browser:
            await self.context.close()
            await self.browser.close()
            await self.playwright.stop()
