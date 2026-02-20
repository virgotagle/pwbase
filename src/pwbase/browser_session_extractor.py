"""
BrowserSessionExtractor
=======================
Extends ``Browser`` with the ability to intercept JSON responses and convert
them into authenticated ``requests.Session`` objects.

Usage::

    async with BrowserSessionExtractor(BrowserConfig(type=BrowserType.STEALTH)) as browser:
        page = await browser.get_page()
        await browser.start_recording(page)
        await page.goto("https://example.com")

        response = browser.find_response("api/data")
        session = browser.to_session(response)
"""

import json
import logging
from dataclasses import dataclass, field
from typing import cast

import requests
from playwright._impl._api_structures import Cookie
from playwright.async_api import Page, Response

from .browser import Browser
from .browser_config import BrowserConfig


@dataclass
class CapturedResponse:
    url: str
    method: str
    headers: dict[str, str]
    body: dict | list | None
    request_headers: dict[str, str]
    request_post_data: str | None = None
    cookies: list[Cookie] = field(default_factory=list)


class BrowserSessionExtractor(Browser):
    def __init__(self, config: BrowserConfig | None = None):
        super().__init__(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.responses: list[CapturedResponse] = []
        self._page: Page | None = None

    async def start_recording(self, page: Page) -> None:
        """Begin intercepting JSON responses on ``page``."""
        self._page = page
        self.responses.clear()
        page.on("response", self._handle_response)

    def stop_recording(self) -> None:
        """Stop intercepting responses. Safe to call if recording was never started."""
        if self._page:
            self._page.remove_listener("response", self._handle_response)
            self._page = None

    async def _handle_response(self, response: Response) -> None:
        if "application/json" not in response.headers.get("content-type", ""):
            return
        try:
            body = await response.json()
        except json.JSONDecodeError:
            self.logger.warning("Failed to decode JSON from %s", response.url)
            return
        if not self.context:
            self.logger.warning("No browser context available; skipping %s", response.url)
            return
        cookies: list[Cookie] = await self.context.cookies(response.url)
        self.responses.append(
            CapturedResponse(
                url=response.url,
                method=response.request.method,
                headers=dict(await response.all_headers()),
                body=body,
                request_headers=dict(await response.request.all_headers()),
                request_post_data=response.request.post_data,
                cookies=cookies,
            )
        )

    def find_response(self, url_contains: str) -> CapturedResponse | None:
        """Return the most recent captured response whose URL contains ``url_contains``."""
        return next((r for r in reversed(self.responses) if url_contains in r.url), None)

    def find_all_responses(self, url_contains: str) -> list[CapturedResponse]:
        """Return all captured responses whose URL contains ``url_contains``."""
        return [r for r in self.responses if url_contains in r.url]

    async def wait_for_response(self, url_contains: str, timeout: int = 1) -> CapturedResponse:
        """
        Poll until a matching response is captured.

        ``timeout`` controls the poll interval in seconds, not a hard deadline.
        """
        if not self._page:
            raise RuntimeError("No page is being recorded. Call start_recording() first.")
        captured = self.find_response(url_contains)
        while not captured:
            await self._page.wait_for_timeout(1000 * timeout)
            captured = self.find_response(url_contains)
        return captured

    def to_session(self, response: CapturedResponse) -> requests.Session:
        """
        Build an authenticated ``requests.Session`` from a captured response.

        Applies request headers (dropping HTTP/2 pseudo-headers prefixed with ``:``)
        and cookies from the captured response.
        """
        session = requests.Session()
        session.headers.update({k: v for k, v in response.request_headers.items() if not k.startswith(":")})
        for cookie in response.cookies:
            c = cast(dict[str, str], cookie)
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))
        return session
