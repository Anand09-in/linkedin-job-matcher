"""
Shared web search utility — used by both salary_service.py (automatic, FR-5)
and referral_service.py (on-demand). Neither of those is LinkedIn scraping:
this hits a public search engine (DuckDuckGo via ddgs), not LinkedIn itself,
so it carries none of the account-automation risk the LinkedIn adapter does.

ddgs's DDGS().text() is a blocking/synchronous call (real network I/O, not
async-native) — run via asyncio.to_thread so it doesn't block the event loop
the rest of the worker's async tasks share.
"""
from __future__ import annotations

import asyncio

from loguru import logger


def _search_sync(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=max_results))


async def web_search(query: str, max_results: int = 6) -> list[dict]:
    """
    Returns a list of {title, body, href} dicts (ddgs's own result shape) or
    an empty list on failure — callers treat "no results" as a normal,
    non-fatal case (system-design.md §1.1's "fail soft" philosophy extended
    to an external dependency neither service should hard-fail on).
    """
    try:
        results = await asyncio.to_thread(_search_sync, query, max_results)
        logger.debug(f"[web_search] {query!r} -> {len(results)} results")
        return results
    except Exception as e:
        logger.warning(f"[web_search] search failed for {query!r}: {e}")
        return []


def format_snippets(results: list[dict]) -> str:
    """Compact text block for an LLM prompt — same shape v1 used."""
    return "\n".join(
        f"[{r.get('title', '')}]: {(r.get('body') or '')[:300]} ({r.get('href', '')})"
        for r in results
    )
