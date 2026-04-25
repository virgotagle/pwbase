"""Tests for BrowserSessionExtractor."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pwbase import BrowserConfig, BrowserSessionExtractor, BrowserType, CapturedResponse
from pwbase.browser_session_extractor import (
    AllRequestExtractor,
)

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
        cookies=[
            {
                "name": "session",
                "value": "abc123",
                "domain": ".example.com",
                "path": "/",
            }
        ],
    )
    return CapturedResponse(**{**defaults, **kwargs})


def make_mock_response(
    url: str, json_body: dict | None = None, content_type: str = "application/json"
) -> AsyncMock:
    """Build a mock Playwright Response object."""
    body_data = json_body or {"data": "value"}
    response = AsyncMock()
    response.url = url
    response.headers = {"content-type": content_type}
    response.body = AsyncMock(return_value=json.dumps(body_data).encode())
    response.all_headers = AsyncMock(return_value={"content-type": content_type})
    response.request = MagicMock()
    response.request.method = "GET"
    response.request.post_data = None
    response.request.all_headers = AsyncMock(
        return_value={"authorization": "Bearer token"}
    )
    return response


def make_all_mock_response(
    url: str,
    method: str = "GET",
    content_type: str = "application/json",
    body: bytes | None = None,
) -> AsyncMock:
    """Build a mock Playwright Response for AllRequestExtractor tests."""
    if body is None:
        if "application/json" in content_type:
            body = json.dumps({"data": "value"}).encode()
        else:
            body = b"body content"
    response = AsyncMock()
    response.url = url
    response.headers = {"content-type": content_type}
    response.body = AsyncMock(return_value=body)
    response.all_headers = AsyncMock(return_value={"content-type": content_type})
    response.request.method = method
    response.request.post_data = None
    response.request.all_headers = AsyncMock(
        return_value={"authorization": "Bearer token"}
    )
    return response


def make_all_extractor(**kwargs) -> AllRequestExtractor:
    """Build an AllRequestExtractor with default config."""
    return AllRequestExtractor(BrowserConfig(type=BrowserType.DEFAULT), **kwargs)


# ── Recording ────────────────────────────────────────────────────────────────


class TestRecording:
    """Tests for recording lifecycle methods."""

    async def test_start_recording_clears_responses(
        self, mock_async_playwright, mock_page
    ):
        """Verify start_recording resets any previously captured responses."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                browser.responses = [make_captured_response()]
                await browser.start_recording(mock_page)
                assert browser.responses == []

    async def test_start_recording_attaches_listener(
        self, mock_async_playwright, mock_page
    ):
        """Verify start_recording registers the response handler on the page."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                mock_page.on.assert_called_once_with(
                    "response",
                    browser._handle_response,  # type: ignore[reportPrivateUsage]  # pylint: disable=protected-access
                )

    async def test_stop_recording_removes_listener(
        self, mock_async_playwright, mock_page
    ):
        """Verify stop_recording detaches the listener and clears the page reference."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                browser.stop_recording()
                mock_page.remove_listener.assert_called_once_with(
                    "response",
                    browser._handle_response,  # type: ignore[reportPrivateUsage]  # pylint: disable=protected-access
                )
                assert browser._page is None  # pylint: disable=protected-access

    async def test_handle_response_captures_json(
        self, mock_async_playwright, mock_context
    ):
        """Verify JSON responses are captured and stored."""
        mock_response = make_mock_response("https://example.com/api/data")
        mock_context.cookies = AsyncMock(return_value=[])

        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 1
                assert browser.responses[0].url == "https://example.com/api/data"

    async def test_handle_response_ignores_non_json(self, mock_async_playwright):
        """Verify non-JSON responses (e.g. images) are not captured."""
        mock_response = make_mock_response(
            "https://example.com/image.png", content_type="image/png"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_handle_response_ignores_invalid_json(self, mock_async_playwright):
        """Verify responses that fail JSON parsing are silently skipped."""
        mock_response = make_mock_response("https://example.com/api/bad")
        mock_response.body = AsyncMock(return_value=b"not valid json {{{")

        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0


# ── Querying ──────────────────────────────────────────────────────────────────


class TestQuerying:
    """Tests for response lookup and filtering methods."""

    async def test_find_response_returns_most_recent(self, mock_async_playwright):
        """Verify find_response returns the last captured match for a URL pattern."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                browser.responses = [
                    make_captured_response(
                        url="https://example.com/api/data", body={"v": 1}
                    ),
                    make_captured_response(
                        url="https://example.com/api/data", body={"v": 2}
                    ),
                ]
                result = browser.find_response("api/data")
                assert result is not None
                assert result.body == {"v": 2}

    async def test_find_response_returns_none_if_not_found(self, mock_async_playwright):
        """Verify find_response returns None when no URL matches the pattern."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                result = browser.find_response("api/missing")
                assert result is None

    async def test_find_all_responses(self, mock_async_playwright):
        """Verify find_all_responses returns every captured match for a URL pattern."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
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
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                with pytest.raises(RuntimeError, match="No page is being recorded"):
                    await browser.wait_for_response("api/data")

    async def test_wait_for_response_found_immediately(
        self, mock_async_playwright, mock_page
    ):
        """Verify wait_for_response returns immediately when the response is already captured."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                await browser.start_recording(mock_page)
                browser.responses = [
                    make_captured_response()
                ]  # set AFTER start_recording
                result = await browser.wait_for_response("api/data")
                assert result is not None
                mock_page.wait_for_timeout.assert_not_called()


# ── Session extraction ────────────────────────────────────────────────────────


class TestSessionExtraction:
    """Tests for converting captured responses into requests Session objects."""

    async def test_to_session_sets_headers(self, mock_async_playwright):
        """Verify to_session copies request headers and filters out HTTP/2 pseudo-headers."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                response = make_captured_response(
                    request_headers={"authorization": "Bearer token", ":method": "GET"}
                )
                session = browser.to_session(response)
                assert session.headers["authorization"] == "Bearer token"
                assert ":method" not in session.headers  # pseudo headers filtered out

    async def test_to_session_sets_cookies(self, mock_async_playwright):
        """Verify to_session populates the session cookie jar from captured cookies."""
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_extractor() as browser:
                response = make_captured_response(
                    cookies=[
                        {
                            "name": "session",
                            "value": "abc123",
                            "domain": ".example.com",
                            "path": "/",
                        }
                    ]
                )
                session = browser.to_session(response)
                assert session.cookies.get("session") == "abc123"


# ── AllRequestExtractor — init (sync) ────────────────────────────────────────


def test_all_extractor_default_exclude_content_types():
    """Verify default exclusions include CSS and JavaScript."""
    extractor = AllRequestExtractor()
    assert "text/css" in extractor.exclude_content_types
    assert "text/javascript" in extractor.exclude_content_types
    assert "application/javascript" in extractor.exclude_content_types


def test_all_extractor_custom_exclude_content_types():
    """Verify custom exclusions replace the defaults."""
    extractor = AllRequestExtractor(exclude_content_types=("text/css",))
    assert extractor.exclude_content_types == ("text/css",)
    assert "text/javascript" not in extractor.exclude_content_types


def test_all_extractor_empty_exclude_content_types():
    """Verify an empty exclusion list is accepted."""
    extractor = AllRequestExtractor(exclude_content_types=())
    assert extractor.exclude_content_types == ()


def test_all_extractor_list_converted_to_tuple():
    """Verify a list of exclusions is stored as a tuple."""
    extractor = AllRequestExtractor(
        exclude_content_types=["text/css", "text/javascript"]
    )
    assert isinstance(extractor.exclude_content_types, tuple)


# ── AllRequestExtractor ───────────────────────────────────────────────────────


class TestAllRequestExtractor:
    """Tests for AllRequestExtractor._handle_response and exclusion logic."""

    # -- GET / POST filtering -------------------------------------------------

    async def test_captures_get_request(self, mock_async_playwright):
        """Verify GET requests are captured."""
        mock_response = make_all_mock_response(
            "https://example.com/api/data", method="GET"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 1

    async def test_captures_post_request(self, mock_async_playwright):
        """Verify POST requests are captured."""
        mock_response = make_all_mock_response(
            "https://example.com/api/submit", method="POST"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 1

    async def test_ignores_put_request(self, mock_async_playwright):
        """Verify PUT requests are not captured."""
        mock_response = make_all_mock_response(
            "https://example.com/api/update", method="PUT"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_ignores_delete_request(self, mock_async_playwright):
        """Verify DELETE requests are not captured."""
        mock_response = make_all_mock_response(
            "https://example.com/api/item", method="DELETE"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    # -- Content-type exclusions ----------------------------------------------

    async def test_excludes_css_by_default(self, mock_async_playwright):
        """Verify CSS responses are excluded with default settings."""
        mock_response = make_all_mock_response(
            "https://example.com/styles.css", content_type="text/css"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_excludes_javascript_by_default(self, mock_async_playwright):
        """Verify JavaScript responses are excluded with default settings."""
        mock_response = make_all_mock_response(
            "https://example.com/app.js", content_type="text/javascript"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_excludes_application_javascript_by_default(
        self, mock_async_playwright
    ):
        """Verify application/javascript responses are excluded with default settings."""
        mock_response = make_all_mock_response(
            "https://example.com/bundle.js", content_type="application/javascript"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_excludes_images_by_default(self, mock_async_playwright):
        """Verify image responses are excluded with default settings."""
        mock_response = make_all_mock_response(
            "https://example.com/logo.png", content_type="image/png"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_excludes_fonts_by_default(self, mock_async_playwright):
        """Verify font responses are excluded with default settings."""
        mock_response = make_all_mock_response(
            "https://example.com/font.woff2", content_type="font/woff2"
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor() as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    async def test_captures_css_when_not_excluded(self, mock_async_playwright):
        """Verify CSS is captured when excluded_content_types is empty."""
        mock_response = make_all_mock_response(
            "https://example.com/styles.css",
            content_type="text/css",
            body=b"body { color: red; }",
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 1
                assert browser.responses[0].body == "body { color: red; }"

    # -- Body parsing ---------------------------------------------------------

    async def test_json_body_parsed_as_dict(self, mock_async_playwright):
        """Verify JSON responses are parsed into dicts."""
        payload = {"user": "alice", "token": "xyz"}
        mock_response = make_all_mock_response(
            "https://example.com/api/login",
            content_type="application/json",
            body=json.dumps(payload).encode(),
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert browser.responses[0].body == payload

    async def test_html_body_stored_as_string(self, mock_async_playwright):
        """Verify HTML responses are stored as decoded strings."""
        html = b"<html><body>Hello</body></html>"
        mock_response = make_all_mock_response(
            "https://example.com/page",
            content_type="text/html",
            body=html,
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert browser.responses[0].body == html.decode()

    async def test_plain_text_body_stored_as_string(self, mock_async_playwright):
        """Verify plain text responses are stored as decoded strings."""
        mock_response = make_all_mock_response(
            "https://example.com/health",
            content_type="text/plain",
            body=b"OK",
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert browser.responses[0].body == "OK"

    async def test_body_error_silently_skipped(self, mock_async_playwright):
        """Verify responses that fail body retrieval are silently skipped."""
        mock_response = make_all_mock_response("https://example.com/api/data")
        mock_response.body = AsyncMock(side_effect=Exception("network error"))
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                assert len(browser.responses) == 0

    # -- Captured response fields ---------------------------------------------

    async def test_captured_response_fields(self, mock_async_playwright):
        """Verify all CapturedResponse fields are populated correctly."""
        payload = {"id": 1}
        mock_response = make_all_mock_response(
            "https://example.com/api/item",
            method="POST",
            content_type="application/json",
            body=json.dumps(payload).encode(),
        )
        mock_response.request.post_data = '{"id": 1}'
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with make_all_extractor(exclude_content_types=()) as browser:
                await browser._handle_response(mock_response)  # pylint: disable=protected-access
                captured = browser.responses[0]
                assert captured.url == "https://example.com/api/item"
                assert captured.method == "POST"
                assert captured.body == payload
                assert captured.request_post_data == '{"id": 1}'
