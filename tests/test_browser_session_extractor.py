"""Tests for BrowserSessionExtractor."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from pwbase import BrowserConfig, BrowserSessionExtractor, BrowserType, CapturedResponse

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_extractor(**kwargs) -> BrowserSessionExtractor:
    """Build a BrowserSessionExtractor with default config overrides."""
    return BrowserSessionExtractor(BrowserConfig(type=BrowserType.DEFAULT, **kwargs))


def make_captured_response(**kwargs) -> CapturedResponse:
    """Create a CapturedResponse with defaults for test assertions."""
    defaults = dict(
        url="https://example.com/api/data",
        method="GET",
        headers={"content-type": "application/json"},
        body={"key": "value"},
        request_headers={"authorization": "Bearer token", ":method": "GET"},
        request_post_data=None,
        cookies=[{"name": "session", "value": "abc123", "domain": ".example.com", "path": "/"}],
    )
    return CapturedResponse(**{**defaults, **kwargs})


def make_mock_response(url: str, json_body: dict | None = None, content_type: str = "application/json") -> AsyncMock:
    """Build a mock Playwright Response object."""
    response = AsyncMock()
    response.url = url
    response.headers = {"content-type": content_type}
    response.json = AsyncMock(return_value=json_body or {"data": "value"})
    response.all_headers = AsyncMock(return_value={"content-type": content_type})
    response.request.method = "GET"
    response.request.post_data = None
    response.request.all_headers = AsyncMock(return_value={"authorization": "Bearer token"})
    return response


# ── Recording ────────────────────────────────────────────────────────────────


class TestRecording:
    """Tests for recording lifecycle methods."""

    async def test_start_recording_clears_responses(self, mock_async_playwright, mock_page):
        """Verify start_recording resets any previously captured responses."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                browser.responses = [make_captured_response()]
                await browser.start_recording(mock_page)
                assert browser.responses == []

    async def test_start_recording_attaches_listener(self, mock_async_playwright, mock_page):
        """Verify start_recording registers the response handler on the page."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                mock_page.on.assert_called_once_with(
                    "response", browser._handle_response  # type: ignore[reportPrivateUsage]  # pylint: disable=protected-access
                )

    async def test_stop_recording_removes_listener(self, mock_async_playwright, mock_page):
        """Verify stop_recording detaches the listener and clears the page reference."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                browser.stop_recording()
                mock_page.remove_listener.assert_called_once_with(
                    "response", browser._handle_response  # type: ignore[reportPrivateUsage]  # pylint: disable=protected-access
                )
                assert browser._page is None  # pylint: disable=protected-access

    async def test_handle_response_captures_json(self, mock_async_playwright, mock_context):
        """Verify JSON responses are captured and stored."""
        mock_response = make_mock_response("https://example.com/api/data")
        mock_context.cookies = AsyncMock(return_value=[])

        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 1
                assert browser.responses[0].url == "https://example.com/api/data"

    async def test_handle_response_ignores_non_json(self, mock_async_playwright):
        """Verify non-JSON responses (e.g. images) are not captured."""
        mock_response = make_mock_response("https://example.com/image.png", content_type="image/png")
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_handle_response_ignores_invalid_json(self, mock_async_playwright):
        """Verify responses that fail JSON parsing are silently skipped."""
        mock_response = make_mock_response("https://example.com/api/bad")
        mock_response.json = AsyncMock(side_effect=json.JSONDecodeError("invalid json", "", 0))

        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0


# ── Querying ──────────────────────────────────────────────────────────────────


class TestQuerying:
    """Tests for response lookup and filtering methods."""

    async def test_find_response_returns_most_recent(self, mock_async_playwright):
        """Verify find_response returns the last captured match for a URL pattern."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                browser.responses = [
                    make_captured_response(url="https://example.com/api/data", body={"v": 1}),
                    make_captured_response(url="https://example.com/api/data", body={"v": 2}),
                ]
                result = browser.find_response("api/data")
                assert result is not None
                assert result.body == {"v": 2}

    async def test_find_response_returns_none_if_not_found(self, mock_async_playwright):
        """Verify find_response returns None when no URL matches the pattern."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                result = browser.find_response("api/missing")
                assert result is None

    async def test_find_all_responses(self, mock_async_playwright):
        """Verify find_all_responses returns every captured match for a URL pattern."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                browser.responses = [
                    make_captured_response(url="https://example.com/api/data"),
                    make_captured_response(url="https://example.com/api/other"),
                    make_captured_response(url="https://example.com/api/data"),
                ]
                results = browser.find_all_responses("api/data")
                assert len(results) == 2

    async def test_wait_for_response_no_page(self, mock_async_playwright):
        """Verify wait_for_response raises RuntimeError when no page is being recorded."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                with pytest.raises(RuntimeError, match="No page is being recorded"):
                    await browser.wait_for_response("api/data")

    async def test_wait_for_response_found_immediately(self, mock_async_playwright, mock_page):
        """Verify wait_for_response returns immediately when the response is already captured."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                browser.responses = [make_captured_response()]  # set AFTER start_recording
                result = await browser.wait_for_response("api/data")
                assert result is not None
                mock_page.wait_for_timeout.assert_not_called()


# ── Session extraction ────────────────────────────────────────────────────────


class TestSessionExtraction:
    """Tests for converting captured responses into requests Session objects."""

    async def test_to_session_sets_headers(self, mock_async_playwright):
        """Verify to_session copies request headers and filters out HTTP/2 pseudo-headers."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                response = make_captured_response(request_headers={"authorization": "Bearer token", ":method": "GET"})
                session = browser.to_session(response)
                assert session.headers["authorization"] == "Bearer token"
                assert ":method" not in session.headers  # pseudo headers filtered out

    async def test_to_session_sets_cookies(self, mock_async_playwright):
        """Verify to_session populates the session cookie jar from captured cookies."""
        with patch("pwbase.browser.async_playwright", return_value=mock_async_playwright):
            async with make_extractor() as browser:
                response = make_captured_response(
                    cookies=[{"name": "session", "value": "abc123", "domain": ".example.com", "path": "/"}]
                )
                session = browser.to_session(response)
                assert session.cookies.get("session") == "abc123"
