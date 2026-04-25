"""
BrowserHarExtractor
===================
Extends ``Browser`` with Playwright's built-in HAR recording.  The HAR file
is finalized automatically when the browser context closes (i.e. when the
async context manager exits or ``stop()`` is called).

Usage::

    async with BrowserHarExtractor(
        BrowserConfig(type=BrowserType.STEALTH),
        har_path="artifacts/session.har",
    ) as browser:
        page = await browser.get_page()
        await page.goto("https://example.com")

    # session.har is ready on disk after the context manager exits

Notes:
    - HAR recording is not available in CDP mode because context options are
      applied only when creating a new context.
    - ``har_mode`` controls entry granularity: ``"minimal"`` (default) records
      request/response metadata only; ``"full"`` also records request bodies.
    - ``har_content`` controls whether response bodies are embedded directly in
      the HAR (``"embed"``, the default) or referenced as separate files
      (``"attach"``).  Use ``"omit"`` to skip bodies entirely.
    - ``har_url_filter`` accepts a URL glob string or compiled ``re.Pattern``.
      Only matching URLs are recorded.  Omit to record all traffic.
"""

import re
from pathlib import Path
from typing import Any

from .browser import Browser
from .browser_config import BrowserConfig
from .browser_type import BrowserType


class BrowserHarExtractor(Browser):
    def __init__(
        self,
        config: BrowserConfig | None = None,
        *,
        har_path: str | Path = "traffic.har",
        har_mode: str = "minimal",
        har_content: str = "embed",
        har_url_filter: str | re.Pattern[str] | None = None,
    ):
        super().__init__(config)
        self.har_path = Path(har_path)
        self.har_mode = har_mode
        self.har_content = har_content
        self.har_url_filter = har_url_filter

    async def start(self) -> None:
        if self.config.type == BrowserType.CDP:
            raise RuntimeError(
                "HAR recording is not supported in CDP mode because context options "
                "are applied only when creating a new context."
            )
        await super().start()

    async def _context_options(self) -> dict[str, Any]:
        options = await super()._context_options()
        self.har_path.parent.mkdir(parents=True, exist_ok=True)
        options["record_har_path"] = str(self.har_path)
        options["record_har_mode"] = self.har_mode
        options["record_har_content"] = self.har_content
        if self.har_url_filter is not None:
            options["record_har_url_filter"] = self.har_url_filter
        return options
