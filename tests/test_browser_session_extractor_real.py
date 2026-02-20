"""Real (non-mock) integration tests for BrowserSessionExtractor.

Split into two groups:

* ``TestPureInMemory`` — exercises methods that operate entirely on in-memory
  state (``find_response``, ``find_all_responses``, ``to_session``, etc.).
  No browser is launched; the extractor is instantiated but never started.

* ``TestRecordingReal`` — exercises the recording pipeline with an actual
  headless Chromium instance.  ``page.route()`` is used to serve controlled
  JSON (and non-JSON) responses at ``https://test.internal/...`` URLs so the
  tests are hermetic and require no external network access.
"""

import asyncio
import json

import pytest
import requests

from pwbase import BrowserConfig, BrowserSessionExtractor, BrowserType, CapturedResponse

pytestmark = pytest.mark.asyncio

# ── Shared helpers ────────────────────────────────────────────────────────────


def _extractor(**kwargs) -> BrowserSessionExtractor:
    return BrowserSessionExtractor(BrowserConfig(type=BrowserType.DEFAULT, headless=True, **kwargs))


def _response(**kwargs) -> CapturedResponse:
    defaults = dict(
        url="https://example.com/api/data",
        method="GET",
        headers={"content-type": "application/json"},
        body={"key": "value"},
        request_headers={"authorization": "Bearer token", ":method": "GET"},
        request_post_data=None,
        cookies=[],
    )
    return CapturedResponse(**{**defaults, **kwargs})


async def _route_json(route, body: dict) -> None:
    """Route handler that fulfills with JSON."""
    await route.fulfill(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(body),
    )


async def _route_html(route) -> None:
    """Route handler that fulfills with plain HTML."""
    await route.fulfill(
        status=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body="<html><body>Hello</body></html>",
    )


def _json_handler(body: dict):
    """Return a one-parameter route handler that fulfills with ``body`` as JSON.

    Playwright inspects the arity of the handler.  A two-parameter handler
    (``route, request``) receives the live ``Request`` object as its second
    argument, so any default-arg trick like ``lambda route, b=body: ...``
    breaks — ``b`` gets overwritten with the ``Request`` object.  This factory
    creates a proper closure so the handler has exactly one parameter.
    """
    async def handler(route):
        await _route_json(route, body)
    return handler


async def _goto_and_wait(page, url: str, extractor: "BrowserSessionExtractor", expected: int = 1) -> None:
    """Navigate to ``url`` and poll until ``extractor.responses`` reaches ``expected`` length.

    Playwright fires the "response" event and schedules ``_handle_response`` as
    an asyncio task.  ``page.goto()`` resolves before that task completes, so
    we need to yield to the event loop and poll until the handler finishes.
    """
    await page.goto(url)
    deadline = 3.0  # seconds
    interval = 0.02
    elapsed = 0.0
    while len(extractor.responses) < expected and elapsed < deadline:
        await asyncio.sleep(interval)
        elapsed += interval


# ── Pure in-memory tests (no browser) ────────────────────────────────────────


class TestPureInMemory:
    """Methods that operate on ``extractor.responses`` or ``CapturedResponse``
    objects directly — no Playwright required."""

    # ── Initial state ─────────────────────────────────────────────────────────

    async def test_initial_responses_empty(self):
        """A freshly created extractor has an empty responses list."""
        extractor = _extractor()
        assert extractor.responses == []

    async def test_initial_page_is_none(self):
        """No page is recorded until start_recording() is called."""
        extractor = _extractor()
        assert extractor._page is None  # pylint: disable=protected-access

    # ── stop_recording guard ──────────────────────────────────────────────────

    async def test_stop_recording_before_start_is_safe(self):
        """stop_recording() is a no-op when recording was never started."""
        extractor = _extractor()
        extractor.stop_recording()  # must not raise

    # ── find_response ─────────────────────────────────────────────────────────

    async def test_find_response_returns_most_recent_match(self):
        """find_response returns the last response whose URL contains the pattern."""
        extractor = _extractor()
        extractor.responses = [
            _response(url="https://example.com/api/data", body={"v": 1}),
            _response(url="https://example.com/api/data", body={"v": 2}),
        ]
        result = extractor.find_response("api/data")
        assert result is not None
        assert result.body == {"v": 2}

    async def test_find_response_returns_none_when_no_match(self):
        """find_response returns None when no URL matches the pattern."""
        extractor = _extractor()
        extractor.responses = [_response()]
        assert extractor.find_response("api/missing") is None

    async def test_find_response_returns_none_on_empty_list(self):
        """find_response returns None when the responses list is empty."""
        extractor = _extractor()
        assert extractor.find_response("api/data") is None

    async def test_find_response_partial_url_match(self):
        """find_response matches any substring of the URL."""
        extractor = _extractor()
        extractor.responses = [_response(url="https://example.com/api/v2/users/123")]
        assert extractor.find_response("v2/users") is not None

    # ── find_all_responses ────────────────────────────────────────────────────

    async def test_find_all_responses_returns_all_matches(self):
        """find_all_responses returns every response matching the pattern."""
        extractor = _extractor()
        extractor.responses = [
            _response(url="https://example.com/api/data"),
            _response(url="https://example.com/api/other"),
            _response(url="https://example.com/api/data"),
        ]
        results = extractor.find_all_responses("api/data")
        assert len(results) == 2

    async def test_find_all_responses_empty_when_no_match(self):
        """find_all_responses returns an empty list when no URLs match."""
        extractor = _extractor()
        extractor.responses = [_response()]
        assert extractor.find_all_responses("api/missing") == []

    async def test_find_all_responses_preserves_order(self):
        """find_all_responses preserves capture order (oldest first)."""
        extractor = _extractor()
        extractor.responses = [
            _response(url="https://example.com/api/data", body={"v": 1}),
            _response(url="https://example.com/api/data", body={"v": 2}),
        ]
        results = extractor.find_all_responses("api/data")
        assert [r.body for r in results] == [{"v": 1}, {"v": 2}]

    # ── wait_for_response guard ───────────────────────────────────────────────

    async def test_wait_for_response_no_page_raises(self):
        """wait_for_response raises RuntimeError when no page is being recorded."""
        extractor = _extractor()
        with pytest.raises(RuntimeError, match="No page is being recorded"):
            await extractor.wait_for_response("api/data")

    # ── to_session ────────────────────────────────────────────────────────────

    async def test_to_session_returns_requests_session(self):
        """to_session returns a requests.Session instance."""
        extractor = _extractor()
        session = extractor.to_session(_response())
        assert isinstance(session, requests.Session)

    async def test_to_session_copies_request_headers(self):
        """to_session copies non-pseudo request headers onto the session."""
        extractor = _extractor()
        resp = _response(request_headers={"authorization": "Bearer abc", "accept": "application/json"})
        session = extractor.to_session(resp)
        assert session.headers["authorization"] == "Bearer abc"
        assert session.headers["accept"] == "application/json"

    async def test_to_session_filters_pseudo_headers(self):
        """HTTP/2 pseudo-headers (prefixed with ':') are excluded from the session."""
        extractor = _extractor()
        resp = _response(request_headers={":method": "GET", ":path": "/", "authorization": "Bearer x"})
        session = extractor.to_session(resp)
        assert ":method" not in session.headers
        assert ":path" not in session.headers

    async def test_to_session_sets_cookies(self):
        """to_session populates the cookie jar from captured cookies."""
        extractor = _extractor()
        resp = _response(cookies=[
            {"name": "session", "value": "abc123", "domain": ".example.com", "path": "/"},
        ])
        session = extractor.to_session(resp)
        assert session.cookies.get("session") == "abc123"

    async def test_to_session_multiple_cookies(self):
        """All captured cookies are added to the session cookie jar."""
        extractor = _extractor()
        resp = _response(cookies=[
            {"name": "a", "value": "1", "domain": ".example.com", "path": "/"},
            {"name": "b", "value": "2", "domain": ".example.com", "path": "/"},
        ])
        session = extractor.to_session(resp)
        assert session.cookies.get("a") == "1"
        assert session.cookies.get("b") == "2"

    async def test_to_session_empty_cookies(self):
        """to_session works cleanly when no cookies were captured."""
        extractor = _extractor()
        resp = _response(cookies=[])
        session = extractor.to_session(resp)
        assert len(list(session.cookies)) == 0


# ── Real browser tests ────────────────────────────────────────────────────────


class TestRecordingReal:
    """Recording pipeline tests with a live headless Chromium browser.

    ``page.route()`` intercepts requests to ``https://test.internal/...`` so
    no external network connection is needed.
    """

    async def test_start_recording_clears_previous_responses(self):
        """start_recording() resets the responses list before attaching the handler."""
        async with _extractor() as extractor:
            page = await extractor.get_page()
            extractor.responses = [_response()]  # pre-populate

            await extractor.start_recording(page)

            assert extractor.responses == []

    async def test_start_recording_sets_page(self):
        """start_recording() stores the page reference."""
        async with _extractor() as extractor:
            page = await extractor.get_page()
            await extractor.start_recording(page)
            assert extractor._page is page  # pylint: disable=protected-access

    async def test_stop_recording_clears_page_reference(self):
        """stop_recording() removes the page reference."""
        async with _extractor() as extractor:
            page = await extractor.get_page()
            await extractor.start_recording(page)
            extractor.stop_recording()
            assert extractor._page is None  # pylint: disable=protected-access

    async def test_captures_json_response(self):
        """A JSON response from a routed URL is captured in extractor.responses."""
        async with _extractor() as extractor:
            page = await extractor.get_page()
            payload = {"hello": "world", "count": 42}

            await page.route("https://test.internal/api/data",
                             lambda route: _route_json(route, payload))
            await extractor.start_recording(page)
            await _goto_and_wait(page, "https://test.internal/api/data", extractor)

            assert len(extractor.responses) == 1
            captured = extractor.responses[0]
            assert captured.url == "https://test.internal/api/data"
            assert captured.body == payload

    async def test_captured_response_method(self):
        """The captured response records the correct HTTP method."""
        async with _extractor() as extractor:
            page = await extractor.get_page()

            await page.route("https://test.internal/api/item",
                             lambda route: _route_json(route, {}))
            await extractor.start_recording(page)
            await _goto_and_wait(page, "https://test.internal/api/item", extractor)

            assert extractor.responses[0].method == "GET"

    async def test_ignores_non_json_response(self):
        """Responses with a non-JSON content-type are not captured."""
        async with _extractor() as extractor:
            page = await extractor.get_page()

            await page.route("https://test.internal/page",
                             lambda route: _route_html(route))
            await extractor.start_recording(page)
            await page.goto("https://test.internal/page")

            assert extractor.responses == []

    async def test_captures_multiple_json_responses(self):
        """Each JSON response encountered during recording is captured separately."""
        async with _extractor() as extractor:
            page = await extractor.get_page()
            payloads = [{"n": 1}, {"n": 2}, {"n": 3}]
            urls = [f"https://test.internal/api/item{i}" for i in range(3)]

            for url, body in zip(urls, payloads):
                await page.route(url, _json_handler(body))

            await extractor.start_recording(page)
            for i, url in enumerate(urls, start=1):
                await _goto_and_wait(page, url, extractor, expected=i)

            assert len(extractor.responses) == 3
            assert [r.body for r in extractor.responses] == payloads

    async def test_stop_recording_stops_capturing(self):
        """After stop_recording(), subsequent JSON responses are not captured."""
        async with _extractor() as extractor:
            page = await extractor.get_page()

            await page.route("https://test.internal/api/first",
                             lambda route: _route_json(route, {"n": 1}))
            await page.route("https://test.internal/api/second",
                             lambda route: _route_json(route, {"n": 2}))

            await extractor.start_recording(page)
            await _goto_and_wait(page, "https://test.internal/api/first", extractor, expected=1)
            extractor.stop_recording()
            await page.goto("https://test.internal/api/second")
            await asyncio.sleep(0.1)  # give the (detached) handler a chance to (not) fire

            assert len(extractor.responses) == 1
            assert extractor.responses[0].body == {"n": 1}

    async def test_find_response_after_capture(self):
        """find_response locates a captured response by URL substring."""
        async with _extractor() as extractor:
            page = await extractor.get_page()

            await page.route("https://test.internal/api/users",
                             lambda route: _route_json(route, {"users": []}))
            await extractor.start_recording(page)
            await _goto_and_wait(page, "https://test.internal/api/users", extractor)

            result = extractor.find_response("api/users")
            assert result is not None
            assert result.body == {"users": []}

    async def test_start_recording_twice_resets_responses(self):
        """Calling start_recording() a second time clears previously captured responses."""
        async with _extractor() as extractor:
            page = await extractor.get_page()

            await page.route("https://test.internal/api/a",
                             lambda route: _route_json(route, {"a": 1}))
            await extractor.start_recording(page)
            await _goto_and_wait(page, "https://test.internal/api/a", extractor, expected=1)
            assert len(extractor.responses) == 1

            # Second start_recording resets the list
            await extractor.start_recording(page)
            assert extractor.responses == []
