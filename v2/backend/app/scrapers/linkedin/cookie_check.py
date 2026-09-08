"""
Checks whether a `li_at` cookie still authenticates against real LinkedIn —
distinct from just "is a value present" (Settings previously only checked
that). Confirmed live (Phase 8) that a stale cookie doesn't error or
redirect obviously: LinkedIn silently serves the logged-out public job
search page instead, which has a different DOM entirely (no
`.scaffold-layout__list`), so the adapter's own scrape just quietly reports
"no jobs found" with no indication the session itself was the problem — the
"no jobs found" log line, on its own, is the same for a genuinely job-less
query and an expired cookie.

Uses `/feed/` rather than a job search: any authenticated cookie lands
there directly, while an expired/invalid one gets redirected to `/login`.
Cheaper and more decisive than checking for a jobs-search DOM element,
which real search results can independently affect.

Confirmed live that checking `page.url` immediately after
`wait_until="domcontentloaded"` is flaky: the SAME cookie was reported
valid by one check and invalid by another less than a minute apart.
LinkedIn's redirect to /login for an actually-invalid session appears to
happen via a client-side redirect fired sometime after the initial HTML
loads, not before — `domcontentloaded` can fire while the URL is still
mid-transition. Waiting explicitly for the URL to settle into one of the
two known-terminal patterns (below) fixes that, without the opposite risk
of using `wait_until="networkidle"`: LinkedIn's feed has ongoing background
polling (notifications, presence) that can keep the network "busy"
indefinitely and make networkidle never fire at all.

Shares adapter.py's persistent browser profile (browser.py) rather than a
fresh context of its own — this check and a real scrape should look like
the same one device to LinkedIn, not two different ones.
"""
from __future__ import annotations

import re

from loguru import logger
from playwright.async_api import async_playwright

from app.scrapers.linkedin.browser import launch_linkedin_context

_FEED_URL = "https://www.linkedin.com/feed/"
_TERMINAL_URL_PATTERN = re.compile(r"/(feed|login|authwall|checkpoint)")


async def check_cookie_valid(cookie: str) -> bool:
    async with async_playwright() as pw:
        context = await launch_linkedin_context(pw, cookie)
        try:
            page = await context.new_page()
            await page.goto(_FEED_URL, wait_until="domcontentloaded", timeout=20000)
            try:
                # No-op if the URL already matches (e.g. no redirect
                # happened at all) — only actually waits when a client-side
                # redirect is still in flight.
                await page.wait_for_url(_TERMINAL_URL_PATTERN, timeout=8000)
            except Exception:
                pass  # settled on neither pattern in time — judge whatever URL we're at
            valid = "/feed" in page.url
            logger.info(f"[linkedin] cookie check: {'valid' if valid else 'invalid/expired'} (landed on {page.url})")
            return valid
        finally:
            await context.close()
