"""Shared fixtures for pwbase tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_page():
    """A mock Playwright Page."""
    page = AsyncMock()
    page.on = MagicMock()
    page.remove_listener = MagicMock()
    page.wait_for_timeout = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page):  # pylint: disable=redefined-outer-name
    """A mock Playwright BrowserContext with one page."""
    context = AsyncMock()
    context.pages = [mock_page]
    context.new_page = AsyncMock(return_value=mock_page)
    context.storage_state = AsyncMock()
    context.cookies = AsyncMock(return_value=[])
    context.close = AsyncMock()
    return context


@pytest.fixture
def mock_browser(mock_context):  # pylint: disable=redefined-outer-name
    """A mock Playwright Browser."""
    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=mock_context)
    browser.contexts = [mock_context]
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright(mock_browser):  # pylint: disable=redefined-outer-name
    """A mock Playwright instance."""
    pw = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=mock_browser)
    pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    pw.stop = AsyncMock()
    return pw


@pytest.fixture
def mock_async_playwright(mock_playwright):  # pylint: disable=redefined-outer-name
    """Patch async_playwright() to return mock_playwright."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_playwright)
    cm.__aexit__ = AsyncMock(return_value=None)
    cm.start = AsyncMock(return_value=mock_playwright)
    return cm
