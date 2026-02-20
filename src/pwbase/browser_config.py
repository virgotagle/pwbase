"""
BrowserConfig
=============
Configuration dataclass for ``Browser`` and its subclasses.

CDP-only fields:   ``cdp_url``
Non-CDP fields:    ``headless``, ``state_path``, ``channel``, ``viewport``,
                   ``user_agent``, ``locale``, ``timezone``, ``args``
"""

from dataclasses import dataclass, field
from pathlib import Path

from .browser_type import BrowserType


@dataclass
class BrowserConfig:
    type: BrowserType = BrowserType.DEFAULT
    headless: bool = True
    state_path: Path | None = None
    channel: str = "chrome"
    cdp_url: str = "http://localhost:9222"
    viewport: tuple[int, int] = (1920, 1080)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    )
    locale: str = "en-US"
    timezone: str = "America/New_York"
    args: list[str] = field(
        default_factory=lambda: [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ]
    )
