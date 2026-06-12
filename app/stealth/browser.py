import asyncio
import os
import json
from typing import Optional, Dict
from playwright.async_api import async_playwright, BrowserContext, Page
from playwright_stealth import stealth_async
from app.core.config import settings
import structlog

log = structlog.get_logger(__name__)

class BrowserManager:
    """Manages stealthy Playwright browser sessions for Web-Chat interaction."""
    
    def __init__(self):
        self.pw = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.cookies_path = "app/stealth/cookies.json"

    async def start(self):
        if self.pw:
            return
            
        log.info("starting_stealth_browser", headless=settings.USE_HEADLESS)
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=settings.USE_HEADLESS,
            executable_path=settings.CHROME_PATH,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        # Load existing cookies if any
        initial_cookies = []
        if os.path.exists(self.cookies_path):
            try:
                with open(self.cookies_path, "r") as f:
                    initial_cookies = json.load(f)
            except Exception as e:
                log.warning("failed_to_load_cookies", error=str(e))

        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        if initial_cookies:
            await self.context.add_cookies(initial_cookies)
            
        # Apply stealth to all new pages
        self.context.on("page", lambda page: stealth_async(page))

    async def get_page(self) -> Page:
        if not self.context:
            await self.start()
        page = await self.context.new_page()
        await stealth_async(page)
        return page

    async def save_cookies(self):
        if self.context:
            cookies = await self.context.cookies()
            with open(self.cookies_path, "w") as f:
                json.dump(cookies, f)
            log.info("cookies_saved")

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
        self.pw = self.browser = self.context = None

browser_mgr = BrowserManager()
