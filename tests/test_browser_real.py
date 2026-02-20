"""Real (non-mock) integration tests for Browser.

These tests launch actual Playwright browser processes.  No mocking is used.
All browsers run headless so the suite is CI-friendly.

Skip markers
------------
- Tests in ``TestStealthBrowserReal`` require Google Chrome to be installed
  (BrowserConfig defaults to channel="chrome" for STEALTH mode).  If Chrome
  is not present they will fail with a clear Playwright error.
- Tests in ``TestCdpBrowserReal`` that require a live CDP endpoint are skipped
  automatically unless the environment has one running on localhost:9222.
"""

import json
import socket

import pytest
from playwright.async_api import BrowserContext, Page

from pwbase import Browser, BrowserConfig, BrowserType

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────


def _default(**kwargs) -> Browser:
    return Browser(BrowserConfig(type=BrowserType.DEFAULT, headless=True, **kwargs))


def _stealth(**kwargs) -> Browser:
    return Browser(BrowserConfig(type=BrowserType.STEALTH, headless=True, **kwargs))


def _cdp_available() -> bool:
    """Return True only when a CDP endpoint is reachable on localhost:9222."""
    try:
        with socket.create_connection(("localhost", 9222), timeout=1):
            return True
    except OSError:
        return False


# ── DEFAULT mode ──────────────────────────────────────────────────────────────


class TestDefaultBrowserReal:
    """Real Playwright tests for Browser in DEFAULT mode."""

    async def test_start_creates_context(self):
        """start() sets context to a live BrowserContext."""
        browser = _default()
        try:
            await browser.start()
            assert isinstance(browser.context, BrowserContext)
        finally:
            await browser.stop()

    async def test_stop_clears_internal_state(self):
        """After stop(), all internal references are reset to None."""
        browser = _default()
        await browser.start()
        await browser.stop()

        assert browser._browser is None
        assert browser._playwright is None
        assert browser.context is None
        assert browser._exit_stack is None

    async def test_context_manager_starts_and_stops(self):
        """Async context manager starts the browser on entry and cleans up on exit."""
        async with _default() as browser:
            assert isinstance(browser.context, BrowserContext)

        assert browser.context is None

    async def test_double_start_raises(self):
        """Starting an already-started browser raises RuntimeError."""
        browser = _default()
        await browser.start()
        try:
            with pytest.raises(RuntimeError, match="already started"):
                await browser.start()
        finally:
            await browser.stop()

    async def test_get_page_returns_real_page(self):
        """get_page() returns a live Playwright Page object."""
        async with _default() as browser:
            page = await browser.get_page()
            assert isinstance(page, Page)

    async def test_get_page_index_zero_is_stable(self):
        """Calling get_page(0) twice returns the same page."""
        async with _default() as browser:
            p1 = await browser.get_page(0)
            p2 = await browser.get_page(0)
            assert p1 is p2

    async def test_get_page_not_started_raises(self):
        """get_page() raises RuntimeError when the browser has not been started."""
        browser = _default()
        with pytest.raises(RuntimeError, match="Browser not started"):
            await browser.get_page()

    async def test_stop_before_start_is_safe(self):
        """Calling stop() on a never-started browser does not raise."""
        browser = _default()
        await browser.stop()  # must not raise

    async def test_stop_twice_is_idempotent(self):
        """Calling stop() a second time after a clean shutdown does not raise."""
        browser = _default()
        await browser.start()
        await browser.stop()
        await browser.stop()  # second call must be a no-op

    async def test_save_state_writes_valid_json(self, tmp_path):
        """save_state() writes a Playwright storage-state JSON file."""
        state_file = tmp_path / "state.json"
        async with _default(state_path=state_file) as browser:
            await browser.save_state()

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert "cookies" in data
        assert "origins" in data

    async def test_save_state_path_arg_overrides_config(self, tmp_path):
        """A path argument passed to save_state() takes precedence over config.state_path."""
        config_path = tmp_path / "config_state.json"
        override_path = tmp_path / "override_state.json"

        async with _default(state_path=config_path) as browser:
            await browser.save_state(path=override_path)

        assert override_path.exists()
        assert not config_path.exists()

    async def test_save_state_creates_parent_dirs(self, tmp_path):
        """save_state() creates missing parent directories automatically."""
        nested = tmp_path / "a" / "b" / "state.json"
        async with _default() as browser:
            await browser.save_state(path=nested)

        assert nested.exists()

    async def test_save_state_no_path_raises(self):
        """save_state() raises ValueError when no path is configured or passed."""
        async with _default() as browser:
            with pytest.raises(ValueError, match="No state path provided"):
                await browser.save_state()

    async def test_save_state_not_started_raises(self):
        """save_state() raises RuntimeError before the browser is started."""
        browser = _default()
        with pytest.raises(RuntimeError, match="Browser not started"):
            await browser.save_state()

    async def test_missing_state_path_starts_cleanly(self, tmp_path):
        """Browser starts without error when state_path points to a nonexistent file."""
        missing = tmp_path / "does_not_exist.json"
        async with _default(state_path=missing) as browser:
            assert isinstance(browser.context, BrowserContext)

    async def test_custom_viewport_applied(self):
        """Configured viewport dimensions are reflected on the opened page."""
        config = BrowserConfig(type=BrowserType.DEFAULT, headless=True, viewport=(800, 600))
        async with Browser(config) as browser:
            page = await browser.get_page()
            assert page.viewport_size == {"width": 800, "height": 600}


# ── STEALTH mode ──────────────────────────────────────────────────────────────


class TestStealthBrowserReal:
    """Real Playwright tests for Browser in STEALTH mode.

    Requires Google Chrome (channel='chrome') to be installed.
    """

    async def test_start_creates_context(self):
        """Stealth browser start() yields a live BrowserContext."""
        browser = _stealth()
        try:
            await browser.start()
            assert isinstance(browser.context, BrowserContext)
        finally:
            await browser.stop()

    async def test_stop_clears_internal_state(self):
        """After stopping, all internal references are reset."""
        browser = _stealth()
        await browser.start()
        await browser.stop()

        assert browser._browser is None
        assert browser._playwright is None
        assert browser.context is None
        assert browser._exit_stack is None

    async def test_context_manager(self):
        """Stealth browser works correctly as an async context manager."""
        async with _stealth() as browser:
            assert isinstance(browser.context, BrowserContext)

        assert browser.context is None

    async def test_get_page_returns_real_page(self):
        """get_page() returns a live Page in STEALTH mode."""
        async with _stealth() as browser:
            page = await browser.get_page()
            assert isinstance(page, Page)


# ── CDP mode ──────────────────────────────────────────────────────────────────


class TestCdpBrowserReal:
    """Tests for Browser in CDP mode.

    Most assertions here do not require a live Chrome process — they exercise
    error-guard paths that fire before any network call.  Tests that need a
    real CDP endpoint are skipped when localhost:9222 is unavailable.
    """

    async def test_save_state_raises_without_starting(self):
        """save_state() raises immediately for CDP config — no browser needed."""
        browser = Browser(BrowserConfig(type=BrowserType.CDP))
        with pytest.raises(RuntimeError, match="not supported in CDP mode"):
            await browser.save_state()

    @pytest.mark.skipif(not _cdp_available(), reason="No CDP endpoint on localhost:9222")
    async def test_connects_to_live_cdp_endpoint(self):
        """Browser attaches to an existing Chrome instance via CDP."""
        async with Browser(BrowserConfig(type=BrowserType.CDP)) as browser:
            assert isinstance(browser.context, BrowserContext)

    @pytest.mark.skipif(not _cdp_available(), reason="No CDP endpoint on localhost:9222")
    async def test_cdp_context_not_closed_on_stop(self):
        """Stop() must not close the borrowed CDP context."""
        browser = Browser(BrowserConfig(type=BrowserType.CDP))
        await browser.start()
        ctx = browser.context
        assert ctx is not None
        await browser.stop()
        # If pwbase had called context.close(), accessing .pages would raise.
        # This verifies the borrowed context is still live after stop().
        _ = ctx.pages
