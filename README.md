# pwbase

A lightweight async Playwright wrapper for Python that supports three browser launch strategies and can intercept authenticated HTTP sessions from live browser traffic.

## Features

- Three browser modes: plain Playwright, stealth (bot-detection evasion), and CDP attachment
- Persistent browser state (cookies + localStorage) via `save_state` / `state_path`
- `BrowserSessionExtractor` — intercepts JSON responses and converts them into authenticated `requests.Session` objects
- Fully async, context-manager-friendly API

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Installation

```bash
uv add pwbase
# or
pip install pwbase
```

Install Playwright browsers after installing the package:

```bash
playwright install chromium
```

## Quick Start

```python
import asyncio
from pwbase import Browser, BrowserConfig, BrowserType

async def main():
    async with Browser(BrowserConfig(type=BrowserType.STEALTH)) as browser:
        page = await browser.get_page()
        await page.goto("https://example.com")
        print(await page.title())

asyncio.run(main())
```

## Browser Modes

| Mode | `BrowserType` | Description |
|---|---|---|
| Default | `DEFAULT` | Pure Playwright, no extras |
| Stealth | `STEALTH` | Applies `playwright-stealth` to reduce bot detection signals |
| CDP | `CDP` | Attaches to an existing Chrome instance via Chrome DevTools Protocol |

### Default

```python
Browser(BrowserConfig(type=BrowserType.DEFAULT))
```

### Stealth

```python
Browser(BrowserConfig(type=BrowserType.STEALTH))
```

### CDP

Start Chrome with remote debugging enabled:

```bash
google-chrome --remote-debugging-port=9222
```

Then attach:

```python
Browser(BrowserConfig(type=BrowserType.CDP, cdp_url="http://localhost:9222"))
```

> **Note:** `headless`, `state_path`, `viewport`, and related options are ignored in CDP mode. `save_state()` is not available in CDP mode.

## BrowserConfig Reference

```python
@dataclass
class BrowserConfig:
    type: BrowserType = BrowserType.DEFAULT
    headless: bool = True
    state_path: Path | None = None      # Load/save cookies + localStorage
    channel: str = "chrome"             # Browser channel for STEALTH mode
    cdp_url: str = "http://localhost:9222"
    viewport: tuple[int, int] = (1920, 1080)
    user_agent: str = "..."             # Windows Chrome UA by default
    locale: str = "en-US"
    timezone: str = "America/New_York"
    args: list[str] = [                 # Extra Chromium flags
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ]
```

## Saving and Restoring Browser State

```python
from pathlib import Path
from pwbase import Browser, BrowserConfig, BrowserType

config = BrowserConfig(
    type=BrowserType.STEALTH,
    state_path=Path("state.json"),
)

# First run — log in and save session
async with Browser(config) as browser:
    page = await browser.get_page()
    await page.goto("https://example.com/login")
    # ... perform login ...
    await browser.save_state()

# Subsequent runs — state is restored automatically
async with Browser(config) as browser:
    page = await browser.get_page()
    await page.goto("https://example.com/dashboard")
```

## Session Extraction

`BrowserSessionExtractor` extends `Browser` and intercepts JSON responses in real time. Use it to capture authenticated sessions without manually copying cookies or headers.

```python
from pwbase import BrowserSessionExtractor, BrowserConfig, BrowserType

async with BrowserSessionExtractor(BrowserConfig(type=BrowserType.STEALTH)) as browser:
    page = await browser.get_page()
    await browser.start_recording(page)

    await page.goto("https://example.com")
    # Trigger the API call you want to capture, then:

    response = browser.find_response("api/data")
    if response:
        session = browser.to_session(response)
        r = session.get("https://example.com/api/data")
        print(r.json())
```

### API

| Method | Description |
|---|---|
| `start_recording(page)` | Begin intercepting JSON responses on `page` |
| `stop_recording()` | Stop intercepting; safe to call if never started |
| `find_response(url_contains)` | Return the most recent captured response matching the substring |
| `find_all_responses(url_contains)` | Return all captured responses matching the substring |
| `wait_for_response(url_contains, timeout)` | Poll until a matching response is captured |
| `to_session(response)` | Build an authenticated `requests.Session` from a `CapturedResponse` |

### CapturedResponse Fields

```python
@dataclass
class CapturedResponse:
    url: str
    method: str
    headers: dict[str, str]           # Response headers
    body: dict | list | None          # Parsed JSON body
    request_headers: dict[str, str]   # Request headers (HTTP/2 pseudo-headers excluded from session)
    request_post_data: str | None
    cookies: list[Cookie]
```

## Manual Lifecycle

If you prefer not to use the context manager:

```python
browser = Browser(BrowserConfig())
await browser.start()
page = await browser.get_page()
# ... do work ...
await browser.stop()
```

## Development

```bash
# Install with dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Run tests with output
uv run pytest -v
```

### Project Structure

```
src/pwbase/
├── __init__.py                  # Public API surface
├── browser.py                   # Browser — core async Playwright wrapper
├── browser_config.py            # BrowserConfig dataclass
├── browser_type.py              # BrowserType enum
└── browser_session_extractor.py # BrowserSessionExtractor + CapturedResponse
tests/
├── conftest.py                  # Shared async mock fixtures
├── test_browser.py              # Unit tests for Browser (all three modes)
└── test_browser_session_extractor.py
```

## License

MIT
