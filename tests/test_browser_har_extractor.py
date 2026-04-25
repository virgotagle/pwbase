"""Tests for BrowserHarExtractor.

Split into two groups:

* ``TestBrowserHarExtractorUnit`` — exercises init and the CDP guard without
  launching a real browser.  Uses the shared mock fixtures from conftest.py.

* ``TestBrowserHarExtractorReal`` — launches a real headless Chromium instance
  and asserts that a valid HAR file is written to disk after the context exits.
  ``page.route()`` serves controlled responses so no external network access
  is required.
"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from pwbase import BrowserConfig, BrowserHarExtractor, BrowserType

# ── Helpers ───────────────────────────────────────────────────────────────────


def _extractor(tmp_path: Path, **kwargs) -> BrowserHarExtractor:
    kwargs.setdefault("har_path", tmp_path / "traffic.har")
    return BrowserHarExtractor(
        BrowserConfig(type=BrowserType.DEFAULT, headless=True),
        **kwargs,
    )


async def _route_json(route, body: dict) -> None:
    await route.fulfill(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(body),
    )


# ── Unit tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestBrowserHarExtractorUnit:
    """Init and guard tests that do not require a live browser."""

    def test_default_har_path(self):
        """Default har_path is 'traffic.har'."""
        extractor = BrowserHarExtractor()
        assert extractor.har_path == Path("traffic.har")

    def test_custom_har_path_str(self, tmp_path: Path):
        """A string har_path is converted to a Path."""
        extractor = BrowserHarExtractor(har_path=str(tmp_path / "out.har"))
        assert isinstance(extractor.har_path, Path)
        assert extractor.har_path.name == "out.har"

    def test_custom_har_path_pathlib(self, tmp_path: Path):
        """A Path har_path is stored as-is."""
        extractor = BrowserHarExtractor(har_path=tmp_path / "out.har")
        assert extractor.har_path == tmp_path / "out.har"

    def test_default_har_mode(self):
        """Default har_mode is 'minimal'."""
        extractor = BrowserHarExtractor()
        assert extractor.har_mode == "minimal"

    def test_default_har_content(self):
        """Default har_content is 'embed'."""
        extractor = BrowserHarExtractor()
        assert extractor.har_content == "embed"

    def test_default_har_url_filter_is_none(self):
        """Default har_url_filter is None."""
        extractor = BrowserHarExtractor()
        assert extractor.har_url_filter is None

    def test_custom_har_url_filter_string(self):
        """A string har_url_filter is stored as-is."""
        extractor = BrowserHarExtractor(har_url_filter="**/api/**")
        assert extractor.har_url_filter == "**/api/**"

    def test_custom_har_url_filter_pattern(self):
        """A compiled re.Pattern har_url_filter is stored as-is."""
        pattern = re.compile(r".*/api/.*")
        extractor = BrowserHarExtractor(har_url_filter=pattern)
        assert extractor.har_url_filter is pattern

    async def test_cdp_mode_raises_on_start(self, mock_async_playwright):
        """start() raises RuntimeError immediately in CDP mode."""
        extractor = BrowserHarExtractor(BrowserConfig(type=BrowserType.CDP))
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            with pytest.raises(RuntimeError, match="CDP mode"):
                await extractor.start()

    async def test_context_options_include_har_fields(
        self, mock_async_playwright, tmp_path: Path
    ):
        """_context_options() includes all four HAR keys when url_filter is set."""
        pattern = re.compile(r".*/api/.*")
        extractor = BrowserHarExtractor(
            BrowserConfig(type=BrowserType.DEFAULT),
            har_path=tmp_path / "out.har",
            har_mode="full",
            har_content="omit",
            har_url_filter=pattern,
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with extractor:
                options = await extractor._context_options()  # pylint: disable=protected-access
                assert options["record_har_path"] == str(tmp_path / "out.har")
                assert options["record_har_mode"] == "full"
                assert options["record_har_content"] == "omit"
                assert options["record_har_url_filter"] is pattern

    async def test_context_options_omit_url_filter_when_none(
        self, mock_async_playwright, tmp_path: Path
    ):
        """_context_options() does not include 'record_har_url_filter' when unset."""
        extractor = BrowserHarExtractor(
            BrowserConfig(type=BrowserType.DEFAULT),
            har_path=tmp_path / "out.har",
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with extractor:
                options = await extractor._context_options()  # pylint: disable=protected-access
                assert "record_har_url_filter" not in options

    async def test_har_parent_dir_created(self, mock_async_playwright, tmp_path: Path):
        """start() creates intermediate directories for har_path if they do not exist."""
        nested = tmp_path / "a" / "b" / "session.har"
        extractor = BrowserHarExtractor(
            BrowserConfig(type=BrowserType.DEFAULT),
            har_path=nested,
        )
        with patch(
            "pwbase.browser.async_playwright", return_value=mock_async_playwright
        ):
            async with extractor:
                await extractor._context_options()  # pylint: disable=protected-access
                assert nested.parent.exists()


# ── Real browser tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestBrowserHarExtractorReal:
    """End-to-end tests with a live headless Chromium browser.

    ``page.route()`` intercepts requests to ``https://test.internal/...`` so
    no external network connection is needed.
    """

    async def test_har_file_created_after_exit(self, tmp_path: Path):
        """A HAR file exists on disk after the context manager exits."""
        har = tmp_path / "session.har"
        async with _extractor(tmp_path, har_path=har) as browser:
            page = await browser.get_page()
            await page.route(
                "https://test.internal/api/data",
                lambda route: _route_json(route, {"hello": "world"}),
            )
            await page.goto("https://test.internal/api/data")

        assert har.exists()
        assert har.stat().st_size > 0

    async def test_har_file_is_valid_json(self, tmp_path: Path):
        """The generated HAR file contains valid JSON."""
        har = tmp_path / "session.har"
        async with _extractor(tmp_path, har_path=har) as browser:
            page = await browser.get_page()
            await page.route(
                "https://test.internal/api/data",
                lambda route: _route_json(route, {"ping": "pong"}),
            )
            await page.goto("https://test.internal/api/data")

        with har.open("r", encoding="utf-8") as file:
            data = json.load(file)

        assert "log" in data
        assert "entries" in data["log"]

    async def test_har_entries_contain_request_url(self, tmp_path: Path):
        """At least one HAR entry records the URL that was navigated to."""
        har = tmp_path / "session.har"
        target = "https://test.internal/api/items"
        async with _extractor(tmp_path, har_path=har) as browser:
            page = await browser.get_page()
            await page.route(
                target,
                lambda route: _route_json(route, {"items": []}),
            )
            await page.goto(target)

        with har.open("r", encoding="utf-8") as file:
            data = json.load(file)

        urls = [e["request"]["url"] for e in data["log"]["entries"]]
        assert any(target in url for url in urls)

    async def test_har_url_filter_limits_entries(self, tmp_path: Path):
        """Only URLs matching har_url_filter appear in the HAR entries."""
        har = tmp_path / "filtered.har"
        async with BrowserHarExtractor(
            BrowserConfig(type=BrowserType.DEFAULT, headless=True),
            har_path=har,
            har_url_filter="**/api/**",
        ) as browser:
            page = await browser.get_page()
            await page.route(
                "https://test.internal/api/data",
                lambda route: _route_json(route, {"filtered": True}),
            )
            await page.goto("https://test.internal/api/data")

        with har.open("r", encoding="utf-8") as file:
            data = json.load(file)

        urls = [e["request"]["url"] for e in data["log"]["entries"]]
        for url in urls:
            assert "/api/" in url

    async def test_har_not_created_before_exit(self, tmp_path: Path):
        """The HAR file does not yet exist (or is empty) while still inside the context."""
        har = tmp_path / "session.har"
        async with _extractor(tmp_path, har_path=har) as browser:
            page = await browser.get_page()
            await page.route(
                "https://test.internal/api/data",
                lambda route: _route_json(route, {}),
            )
            await page.goto("https://test.internal/api/data")
            # HAR is flushed only on context close, not during navigation
            size_during = har.stat().st_size if har.exists() else 0

        size_after = har.stat().st_size
        assert size_after > size_during
