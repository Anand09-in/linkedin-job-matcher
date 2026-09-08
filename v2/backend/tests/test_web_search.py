"""Unit tests for the shared web_search utility — ddgs itself mocked, no
real network call. Both salary_service.py and referral_service.py depend on
this behaving correctly (especially failing soft, not raising)."""
from __future__ import annotations

from unittest.mock import patch

from app.services.web_search import format_snippets, web_search


async def test_web_search_returns_results_on_success():
    fake_results = [{"title": "T1", "body": "B1", "href": "https://x/1"}]
    with patch("app.services.web_search._search_sync", return_value=fake_results):
        results = await web_search("some query")
    assert results == fake_results


async def test_web_search_fails_soft_returns_empty_list():
    """A search failure (network error, ddgs rate limit, etc.) is a normal,
    non-fatal case — callers (salary/referral services) must not crash."""
    with patch("app.services.web_search._search_sync", side_effect=RuntimeError("simulated search failure")):
        results = await web_search("some query")
    assert results == []


def test_format_snippets_produces_compact_text():
    results = [
        {"title": "Data Engineer salary Bangalore", "body": "12-18 LPA for mid-level roles" * 20, "href": "https://x/1"},
    ]
    text = format_snippets(results)
    assert "Data Engineer salary Bangalore" in text
    assert "https://x/1" in text
    # Body is truncated to 300 chars per snippet, not dumped in full.
    assert len(text) < len(results[0]["body"])


def test_format_snippets_empty_list_returns_empty_string():
    assert format_snippets([]) == ""
