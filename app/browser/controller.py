"""Playwright controller (plan section 3): the only module allowed to touch the browser."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, Page, Playwright, async_playwright


class BrowserController:
    """Thin async wrapper around one Chromium page. Live view comes in M1 proper."""

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self.page: Page | None = None

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self.page = await self._browser.new_page()

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def goto(self, url: str) -> None:
        assert self.page
        await self.page.goto(url, wait_until="domcontentloaded")

    async def fill(self, selector: str, value: str) -> None:
        assert self.page
        await self.page.fill(selector, value)

    async def click(self, selector: str) -> None:
        assert self.page
        await self.page.click(selector)

    async def wait_for_url(self, pattern: str) -> None:
        assert self.page
        await self.page.wait_for_url(pattern)

    async def input_value(self, selector: str) -> str:
        assert self.page
        return await self.page.input_value(selector)

    async def screenshot(self, path: str | Path) -> None:
        assert self.page
        target = Path(path)
        temp = target.with_name(f"{target.stem}_tmp{target.suffix}")
        await self.page.screenshot(path=str(temp), full_page=True)
        temp.replace(target)
