"""Tests for Browser class — DEFAULT, STEALTH, and CDP modes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pwbase import Browser, BrowserConfig, BrowserType

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_browser(browser_type: BrowserType, **kwargs) -> Browser:
    """Create a Browser instance with the given type and optional config kwargs."""
    return Browser(BrowserConfig(type=browser_type, **kwargs))


# ── DEFAULT ──────────────────────────────────────────────────────────────────


class TestDefaultBrowser:
    """Tests for Browser in DEFAULT (standard Playwright) mode."""

    async def test_start_stop(self, mock_async_playwright, mock_playwright, mock_context):
        """Browser starts by launching Chromium and stops by closing the context."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            browser = make_browser(BrowserType.DEFAULT)
            await browser.start()

            assert browser.context is not None
            mock_playwright.chromium.launch.assert_called_once_with(
                headless=True,
                args=browser.config.args,
            )

            await browser.stop()
            mock_context.close.assert_called_once()

    async def test_context_manager(self, mock_async_playwright):
        """Async context manager starts the browser and exposes a live context."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT) as browser:
                assert browser.context is not None

    async def test_get_page_existing(self, mock_async_playwright, mock_page):
        """get_page returns the existing page at the requested index."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT) as browser:
                page = await browser.get_page(0)
                assert page is mock_page

    async def test_get_page_new(self, mock_async_playwright, mock_context):
        """get_page opens a new page when no pages exist in the context."""
        mock_context.pages = []  # no existing pages
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT) as browser:
                await browser.get_page()
                mock_context.new_page.assert_called_once()

    async def test_get_page_not_started(self):
        """get_page raises RuntimeError when called before the browser is started."""
        browser = make_browser(BrowserType.DEFAULT)
        with pytest.raises(RuntimeError, match="Browser not started"):
            await browser.get_page()

    async def test_save_state(self, mock_async_playwright, mock_context, tmp_path):
        """save_state persists storage state to the configured path."""
        state_file = tmp_path / "state.json"
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT, state_path=state_file) as browser:
                await browser.save_state()
                mock_context.storage_state.assert_called_once_with(path=str(state_file))

    async def test_save_state_no_path(self, mock_async_playwright):
        """save_state raises ValueError when no state_path is configured."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT) as browser:
                with pytest.raises(ValueError, match="No state path provided"):
                    await browser.save_state()

    async def test_save_state_not_started(self):
        """save_state raises RuntimeError when called before the browser is started."""
        browser = make_browser(BrowserType.DEFAULT)
        with pytest.raises(RuntimeError, match="Browser not started"):
            await browser.save_state()

    async def test_headless_false(self, mock_async_playwright, mock_playwright):
        """Browser launches with headless=False when configured."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.DEFAULT, headless=False) as browser:
                mock_playwright.chromium.launch.assert_called_once_with(
                    headless=False,
                    args=browser.config.args,
                )


# ── STEALTH ──────────────────────────────────────────────────────────────────


class TestStealthBrowser:
    """Tests for Browser in STEALTH (playwright-stealth) mode."""

    async def test_start_uses_stealth(self, mock_async_playwright, mock_playwright):
        """Browser starts via the Stealth context manager and launches on the chrome channel."""
        mock_stealth_cm = AsyncMock()
        mock_stealth_cm.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_stealth_cm.__aexit__ = AsyncMock(return_value=None)

        mock_stealth = MagicMock()
        mock_stealth.use_async = MagicMock(return_value=mock_stealth_cm)

        with (
            patch("pwbase.browser.async_playwright", return_value=mock_async_playwright),
            patch("pwbase.browser.Stealth", return_value=mock_stealth),
        ):
            async with make_browser(BrowserType.STEALTH) as browser:
                assert browser.context is not None
                mock_playwright.chromium.launch.assert_called_once_with(
                    headless=True,
                    channel="chrome",
                    args=browser.config.args,
                )

    async def test_stop_calls_stealth_exit(self, mock_async_playwright, mock_playwright):
        """Stopping the browser exits the Stealth context manager."""
        mock_stealth_cm = AsyncMock()
        mock_stealth_cm.__aenter__ = AsyncMock(return_value=mock_playwright)
        mock_stealth_cm.__aexit__ = AsyncMock(return_value=None)

        mock_stealth = MagicMock()
        mock_stealth.use_async = MagicMock(return_value=mock_stealth_cm)

        with (
            patch("pwbase.browser.async_playwright", return_value=mock_async_playwright),
            patch("pwbase.browser.Stealth", return_value=mock_stealth),
        ):
            async with make_browser(BrowserType.STEALTH):
                pass
            mock_stealth_cm.__aexit__.assert_called_once()


# ── CDP ───────────────────────────────────────────────────────────────────────


class TestCdpBrowser:
    """Tests for Browser in CDP (Chrome DevTools Protocol) mode."""

    async def test_connects_via_cdp(self, mock_async_playwright, mock_playwright):
        """Browser connects to the default CDP endpoint and exposes a context."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.CDP) as browser:
                mock_playwright.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9222")
                assert browser.context is not None

    async def test_custom_cdp_url(self, mock_async_playwright, mock_playwright):
        """Browser connects to a user-supplied CDP URL instead of the default."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.CDP, cdp_url="http://localhost:9333") as _:
                mock_playwright.chromium.connect_over_cdp.assert_called_once_with("http://localhost:9333")

    async def test_save_state_raises(self, mock_async_playwright):
        """save_state raises RuntimeError because state persistence is not supported in CDP mode."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.CDP) as browser:
                with pytest.raises(RuntimeError, match="not supported in CDP mode"):
                    await browser.save_state()

    async def test_context_not_closed_on_stop(self, mock_async_playwright, mock_context):
        """CDP context is borrowed — it should not be closed by pwbase."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_browser(BrowserType.CDP):
                pass
            mock_context.close.assert_not_called()
