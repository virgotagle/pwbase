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
from dataclasses import asdict, dataclass, field
from pathlib import Path
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

    def to_json_file(self, filename: str = "captured_response.json") -> None:
        """Write this captured response to a JSON file."""
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(asdict(self), file, indent=2)

    @staticmethod
    def from_json_file(filename: str = "captured_response.json") -> "CapturedResponse":
        """Read a JSON file and convert it into a ``CapturedResponse``."""
        if not filename.strip():
            raise ValueError("filename must be a non-empty string")

        path = Path(filename)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {filename}")

        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in file: {filename}") from exc

        if not isinstance(data, dict):
            raise ValueError("CapturedResponse JSON must be an object")

        required_fields = {
            "url",
            "method",
            "headers",
            "body",
            "request_headers",
            "request_post_data",
            "cookies",
        }
        missing_fields = required_fields - set(data)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Missing required fields: {missing}")

        if not isinstance(data["url"], str) or not data["url"]:
            raise ValueError("'url' must be a non-empty string")
        if not isinstance(data["method"], str) or not data["method"]:
            raise ValueError("'method' must be a non-empty string")
        if not isinstance(data["headers"], dict):
            raise ValueError("'headers' must be an object")
        if not isinstance(data["request_headers"], dict):
            raise ValueError("'request_headers' must be an object")
        if data["request_post_data"] is not None and not isinstance(data["request_post_data"], str):
            raise ValueError("'request_post_data' must be a string or null")
        if not isinstance(data["cookies"], list):
            raise ValueError("'cookies' must be an array")
        if data["body"] is not None and not isinstance(data["body"], (dict, list)):
            raise ValueError("'body' must be an object, array, or null")

        normalized_cookies: list[Cookie] = []
        for cookie in data["cookies"]:
            if not isinstance(cookie, dict):
                raise ValueError("Each cookie must be an object")
            if not isinstance(cookie.get("name"), str) or not isinstance(cookie.get("value"), str):
                raise ValueError("Each cookie must include string 'name' and 'value'")
            normalized_cookies.append(cast(Cookie, cookie))

        return CapturedResponse(
            url=data["url"],
            method=data["method"],
            headers=cast(dict[str, str], data["headers"]),
            body=cast(dict | list | None, data["body"]),
            request_headers=cast(dict[str, str], data["request_headers"]),
            request_post_data=cast(str | None, data["request_post_data"]),
            cookies=normalized_cookies,
        )


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

        Applies request headers (dropping HTTP/2 pseudo-headers prefixed with ``:``
        and the raw ``cookie`` header) and cookies from the captured response.

        The ``cookie`` header is excluded because it contains the stale cookie values
        from the original request. The fresh cookies captured after the response
        (including any Set-Cookie updates) are applied via ``session.cookies`` instead,
        which ``requests`` uses to build the correct Cookie header on each outgoing call.
        """
        session = requests.Session()
        session.headers.update(
            {k: v for k, v in response.request_headers.items() if not k.startswith(":") and k.lower() != "cookie"}
        )
        for cookie in response.cookies:
            c = cast(dict[str, str], cookie)
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))
        return session
