"""
Browser
=======
Async Playwright wrapper supporting three launch strategies:

    DEFAULT  — plain Playwright, no extras.
    STEALTH  — wraps playwright-stealth to reduce bot detection.
    CDP      — attaches to an existing Chrome instance via Chrome DevTools Protocol.

Usage::

    # Context manager (recommended)
    async with Browser(BrowserConfig(type=BrowserType.STEALTH)) as browser:
        page = await browser.get_page()

    # Manual lifecycle
    browser = Browser(BrowserConfig(type=BrowserType.CDP))
    await browser.start()
    page = await browser.get_page()
    await browser.stop()

Notes:
    - ``headless``, ``state_path``, ``viewport``, and related options are ignored in CDP mode.
    - ``save_state()`` is not available in CDP mode.
"""

import asyncio
import logging
from contextlib import AsyncExitStack
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from playwright.async_api import Browser as PWBrowser
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from playwright_stealth import Stealth

from .browser_config import BrowserConfig
from .browser_type import BrowserType


class Browser:
    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: PWBrowser | None = None
        self._exit_stack: AsyncExitStack | None = None
        self.context: BrowserContext | None = None
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    async def start(self) -> None:
        if self._browser is not None:
            raise RuntimeError("Browser already started. Call stop() before starting again.")
        self.logger.info("Starting browser in %s mode", self.config.type)
        try:
            match self.config.type:
                case BrowserType.CDP:
                    await self._connect_cdp()
                case BrowserType.STEALTH:
                    await self._launch_stealth()
                case BrowserType.DEFAULT:
                    await self._launch_default()
                case _:
                    raise ValueError(f"Unsupported BrowserType: {self.config.type}")
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Idempotent — safe to call even if the browser was never fully started."""
        self.logger.info("Stopping browser")
        try:
            if self.context and self.config.type != BrowserType.CDP:
                await self.context.close()
        finally:
            try:
                if self._browser:
                    await self._browser.close()
            finally:
                if self._exit_stack:
                    await self._exit_stack.aclose()
                elif self._playwright:
                    await self._playwright.stop()
                self._browser = None
                self.context = None
                self._playwright = None
                self._exit_stack = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def _launch_default(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            args=self.config.args,
        )
        self.context = await self._browser.new_context(**await self._context_options())

    async def _launch_stealth(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._playwright = await self._exit_stack.enter_async_context(Stealth().use_async(async_playwright()))
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            channel=self.config.channel,
            args=self.config.args,
        )
        self.context = await self._browser.new_context(**await self._context_options())

    async def _connect_cdp(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(self.config.cdp_url)
        if not self._browser.contexts:
            raise RuntimeError("CDP browser has no open contexts. Ensure Chrome has at least one window open.")
        self.context = self._browser.contexts[0]

    async def _context_options(self) -> dict[str, Any]:
        cfg = self.config
        path_exists = await asyncio.to_thread(cfg.state_path.exists) if cfg.state_path else False
        storage = str(cfg.state_path) if cfg.state_path and path_exists else None
        if cfg.state_path and not path_exists:
            self.logger.warning("State path %s does not exist; starting without stored state", cfg.state_path)
        w, h = cfg.viewport
        return {
            "viewport": {"width": w, "height": h},
            "user_agent": cfg.user_agent,
            "locale": cfg.locale,
            "timezone_id": cfg.timezone,
            "storage_state": storage,
        }

    async def get_page(self, index: int = 0) -> Page:
        """Return the page at ``index``, creating a new one if it doesn't exist. Not available in CDP mode."""
        if not self.context:
            raise RuntimeError("Browser not started. Call start() or use as async context manager.")
        pages = self.context.pages
        if index < len(pages):
            return pages[index]
        return await self.context.new_page()

    async def save_state(self, path: str | Path | None = None) -> None:
        """Save cookies and localStorage to disk. ``path`` takes precedence over ``config.state_path``."""
        if self.config.type == BrowserType.CDP:
            raise RuntimeError("save_state() is not supported in CDP mode.")
        if not self.context:
            raise RuntimeError("Browser not started. Call start() or use as async context manager.")
        save_path = Path(path) if path else self.config.state_path
        if not save_path:
            raise ValueError("No state path provided.")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info("Saving browser state to %s", save_path)
        await self.context.storage_state(path=str(save_path))
