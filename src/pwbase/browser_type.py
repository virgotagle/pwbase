from enum import Enum


class BrowserType(str, Enum):
    """Browser launch strategy. See ``BrowserConfig`` for mode-specific field availability."""

    DEFAULT = "default"  # Pure Playwright, no extras
    STEALTH = "stealth"  # Avoids bot detection, recommended for production
    CDP = "cdp"  # Attaches to an existing Chrome instance, recommended for development
