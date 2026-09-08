"""
LinkedIn scraper adapter — Playwright-based, owns its DOM selectors directly
instead of depending on the third-party `linkedin-jobs-scraper` library v1
used (system-design.md decision log #3): that library's selector bugs — most
concretely, date_posted coming back empty for every one of the 324 jobs in
v1's database — were unfixable from our side except by forking it.

Session handling: reuses the li_at cookie (same approach v1 took) to hit the
authenticated jobs-search UI, which exposes a `<time datetime="...">` element
this adapter reads directly — fixing the v1 bug at the source rather than
working around it downstream.

`_extract_job` is factored out from the navigation/pagination loop
specifically so it can be exercised directly against a fixture-loaded page in
tests (system-design.md §6: "tested against recorded HTML fixtures, not live
LinkedIn") without mocking Playwright's navigation machinery.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional
from urllib.parse import urlsplit, urlunsplit

from loguru import logger
from playwright.async_api import Locator, Page, async_playwright

from app.core.config import get_settings
from app.scrapers.base import RawJob, ScrapeConfig, batched
from app.scrapers.linkedin import selectors
from app.scrapers.linkedin.url_builder import build_search_url
from app.scrapers.registry import register

_HOME_URL = "https://www.linkedin.com"
_PAGE_SIZE = 25


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        logger.debug(f"[linkedin] unparseable date_posted raw value: {raw!r}")
        return None


_RELATIVE_UNIT_ALIASES: dict[str, str] = {
    "s": "seconds", "sec": "seconds", "second": "seconds",
    "m": "minutes", "min": "minutes", "minute": "minutes",
    "h": "hours", "hr": "hours", "hour": "hours",
    "d": "days", "day": "days",
    "w": "weeks", "wk": "weeks", "week": "weeks",
    "mo": "months", "month": "months",
    "y": "years", "yr": "years", "year": "years",
}


def _parse_relative_time(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """
    Best-effort parse of LinkedIn's human-readable relative time badge
    ("1 day ago", "3w", "2 months ago", ...) into an absolute datetime.

    Confirmed live during Phase 2 testing: the <time> element's `datetime`
    attribute isn't always present — some listings only render this relative
    text with no machine-readable value at all. This is why RawJob keeps
    BOTH date_posted_raw (always set when the site gives us anything) and
    date_posted (only set when we could confidently turn it into a real
    date) — months/years are approximated (30/365 days), so this is good
    enough for filtering/sorting, not display-grade precision. Returns None
    for anything unrecognized rather than guessing.
    """
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    normalized = text.strip().lower()

    if normalized in ("just now", "today"):
        return now
    if normalized == "yesterday":
        return now - timedelta(days=1)

    match = re.match(r"(\d+)\s*([a-z]+)", normalized)
    if not match:
        return None
    amount = int(match.group(1))
    unit_word = match.group(2).rstrip("s")  # "days"/"weeks"/... -> singular
    unit = _RELATIVE_UNIT_ALIASES.get(unit_word)
    if unit is None:
        return None

    if unit == "months":
        return now - timedelta(days=amount * 30)
    if unit == "years":
        return now - timedelta(days=amount * 365)
    return now - timedelta(**{unit: amount})


async def _text_or_none(locator: Locator) -> Optional[str]:
    first = locator.first
    if await first.count() == 0:
        return None
    text = (await first.inner_text()).strip()
    return text or None


def _canonicalize_link(url: str) -> str:
    """
    Strip query params — LinkedIn appends different tracking tokens (trk=,
    trackingId=, refId=, eBP=) to the SAME job's link depending on which
    search result page it appeared on, confirmed against real scraped data
    during Phase 2 testing (the identical job showed up with different query
    strings across pages/locations in one run). Deduping on the raw href
    would silently treat one job as several; /jobs/view/<id>/ — the path —
    is the actual stable identifier, and canonicalizing it here means every
    downstream consumer (this adapter's own in-run dedup, and the DB-level
    unique constraint on Job.link) inherits the fix for free.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _clean_title(raw: str) -> str:
    """
    LinkedIn's title element contains two newline-joined lines for the same
    job (an accessibility/duplicate line, then the real — sometimes more
    complete, e.g. "...with verification" — title). Confirmed against real
    scraped data during Phase 2 testing: v1's third-party library already
    had to work around this the same way (split on '\n', keep index 1).
    """
    parts = raw.split("\n")
    return parts[1].strip() if len(parts) > 1 else parts[0].strip()


async def _is_promoted(card: Locator) -> bool:
    """
    Ported from v1's third-party library, which scanned every <li> in the
    card for exact text "Promoted" — the same technique, same reason: no
    dedicated class exists for this badge. Matters here specifically because
    promoted/sponsored listings carry no posted-date at all, unlike organic
    ones (confirmed live during Phase 2 testing — a batch of results with
    date_posted=None for every job turned out to be entirely promoted
    listings, not an extraction failure).
    """
    items = card.locator(selectors.CARD_LIST_ITEMS)
    count = await items.count()
    for i in range(count):
        text = (await items.nth(i).inner_text()).strip()
        if text == selectors.PROMOTED_LABEL:
            return True
    return False


async def extract_job(page: Page, card: Locator) -> Optional[RawJob]:
    """
    Extract one RawJob from a single job-card Locator already on the page,
    clicking through to load its description panel.

    Pure w.r.t. navigation — takes an already-loaded Page/Locator, so it's
    the unit under test in test_linkedin_adapter.py against a saved fixture.
    """
    link_el = card.locator(selectors.JOB_LINK).first
    if await link_el.count() == 0:
        return None
    href = await link_el.get_attribute("href")
    if not href:
        return None
    absolute = href if href.startswith("http") else f"https://www.linkedin.com{href}"
    link = _canonicalize_link(absolute)

    # Scroll the card into view BEFORE reading any of its fields. LinkedIn's
    # job list lazily hydrates card content (confirmed live during Phase 2
    # testing: date_posted came back populated for only 1/7 real jobs until
    # this reorder) — reading fields from an off-screen, not-yet-hydrated
    # card is exactly how v1's date_posted bug happened, just less visibly
    # (v1 never scrolled per-card at all, so it failed 100% of the time
    # instead of intermittently).
    await link_el.scroll_into_view_if_needed()

    title_raw = await _text_or_none(card.locator(selectors.TITLE)) or ""
    title = _clean_title(title_raw)
    company = await _text_or_none(card.locator(selectors.COMPANY)) or ""
    place = await _text_or_none(card.locator(selectors.PLACE))
    promoted = await _is_promoted(card)

    date_posted_raw: Optional[str] = None
    date_posted: Optional[datetime] = None
    date_el = card.locator(selectors.DATE).first
    try:
        # Not "the element exists" (it may already be attached but still
        # hydrating) — genuinely absent on some listings, so a short timeout
        # that just gives up is correct, not a bug to retry harder on.
        await date_el.wait_for(state="attached", timeout=1500)
        attr_value = await date_el.get_attribute("datetime")
        if attr_value:
            date_posted_raw = attr_value
            date_posted = _parse_date(attr_value)
        else:
            # No machine-readable datetime= at all on this listing — only a
            # human relative-time badge ("1 day ago", "3w"). Confirmed live
            # during Phase 2 testing; not every job card has the attribute.
            text_value = (await date_el.inner_text()).strip()
            if text_value:
                date_posted_raw = text_value
                date_posted = _parse_relative_time(text_value)
    except Exception:
        pass

    # Click through to load (or, on a real search-results page, swap) the
    # description panel for this specific job. Waiting for the ELEMENT to
    # exist is not enough — it's a persistent panel that already exists from
    # the previous job, so that wait resolves instantly without the new
    # job's content having loaded yet (confirmed live: several jobs came
    # back with only "About the job" and nothing else). Wait for the text to
    # actually CHANGE instead.
    description_before = (await _text_or_none(page.locator(selectors.DESCRIPTION))) or ""
    await link_el.click()
    try:
        await page.wait_for_function(
            """([sel, before]) => {
                const el = document.querySelector(sel);
                const text = el ? el.innerText.trim() : '';
                return text.length > 20 && text !== before;
            }""",
            arg=[selectors.DESCRIPTION, description_before],
            timeout=8000,
        )
    except Exception:
        logger.warning(f"[linkedin] description panel did not update for {link}")

    description = await _text_or_none(page.locator(selectors.DESCRIPTION)) or ""

    return RawJob(
        title=title,
        company=company,
        location=place,
        link=link,
        description=description,
        date_posted_raw=date_posted_raw,
        date_posted=date_posted,
        is_promoted=promoted,
    )


async def _resolve_li_at_cookie() -> str:
    """DB-first (Phase 8: UI-editable via Settings, no worker restart needed
    to rotate an expired cookie — the previous LI_AT_COOKIE-env-only setup
    needed one), falling back to the env var for anyone who hasn't set one
    via the UI yet. Same isolated-import pattern as core/llm.py's
    _get_active_llm_setting(), for the same reason: a low-level module like
    this scraper adapter shouldn't hard-depend on the domain/DB layer at
    import time, only when actually asked to scrape."""
    from app.domain.db import AsyncSessionLocal
    from app.domain.repository import Repository

    async with AsyncSessionLocal() as session:
        credential = await Repository(session).get_scraper_credential("linkedin")
    if credential and credential.value:
        return credential.value
    return get_settings().li_at_cookie


@register("linkedin")
class LinkedInScraper:
    site_name = "linkedin"

    async def check_credential(self) -> tuple[bool, str]:
        """
        Optional hook scrape_service.py calls (via hasattr, not a required
        part of the BaseScraper protocol — testsite has no credential at
        all) BEFORE starting a run, as a setup-prerequisite check in the
        same tier as an adapter-connect failure or a resume-parse failure.

        Added directly in response to a real, confusing failure mode: an
        expired li_at cookie doesn't error or redirect obviously — LinkedIn
        silently serves the logged-out public search page instead (no
        `.scaffold-layout__list`), so without this check a run just quietly
        completes with seen=0/saved=0, indistinguishable from "this query
        genuinely has no matches" until someone thinks to check the cookie
        itself (see cookie_check.py's docstring for the full diagnosis).
        """
        from app.scrapers.linkedin.cookie_check import check_cookie_valid

        cookie = await _resolve_li_at_cookie()
        if not cookie:
            return False, "No LinkedIn session cookie configured — set one via Settings in the UI (or LI_AT_COOKIE in .env)."
        if not await check_cookie_valid(cookie):
            return False, "LinkedIn session cookie is invalid or expired — update it via Settings in the UI."
        return True, ""

    async def scrape(self, config: ScrapeConfig) -> AsyncIterator[list[RawJob]]:
        cookie = await _resolve_li_at_cookie()
        if not cookie:
            raise ValueError(
                "No LinkedIn session cookie configured — set one via Settings in the UI (or LI_AT_COOKIE in .env)."
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                await context.add_cookies([{
                    "name": "li_at",
                    "value": cookie,
                    "domain": ".www.linkedin.com",
                    "path": "/",
                }])
                page = await context.new_page()

                async for batch in batched(self._iter_jobs(page, config), config.batch_size):
                    yield batch
            finally:
                await browser.close()

    async def _iter_jobs(self, page: Page, config: ScrapeConfig) -> AsyncIterator[RawJob]:
        await page.goto(_HOME_URL)
        seen_links: set[str] = set()

        for location in config.locations or [""]:
            if len(seen_links) >= config.limit:
                return
            async for raw_job in self._scrape_location(page, config, location):
                if raw_job.link in seen_links:
                    continue
                seen_links.add(raw_job.link)
                yield raw_job
                if len(seen_links) >= config.limit:
                    return

    async def _scrape_location(self, page: Page, config: ScrapeConfig, location: str) -> AsyncIterator[RawJob]:
        start = 0
        collected = 0

        while collected < config.limit:
            url = build_search_url(config.query, location, config.filters, start=start)
            logger.debug(f"[linkedin] opening {url}")
            await page.goto(url)

            try:
                await page.wait_for_selector(selectors.CONTAINER, timeout=8000)
            except Exception:
                logger.info(f"[linkedin] no jobs found for query={config.query!r} location={location!r}")
                return

            cards = page.locator(selectors.JOB_CARD)
            count = await cards.count()
            if count == 0:
                return

            for i in range(count):
                if collected >= config.limit:
                    return
                try:
                    raw_job = await extract_job(page, cards.nth(i))
                except Exception as e:
                    logger.warning(f"[linkedin] failed to extract job at index {i}: {e}")
                    # Confirmed live during Phase 2 testing: a job-card click
                    # can occasionally trigger a full page navigation away
                    # from the search-results list (not just an in-place
                    # panel update), which then breaks every subsequent
                    # locator on this page with "execution context was
                    # destroyed". Recover by returning to this exact search
                    # results page/offset rather than letting one bad click
                    # silently zero out the rest of the batch.
                    if "execution context was destroyed" in str(e).lower() or "navigat" in str(e).lower():
                        logger.info(f"[linkedin] recovering: re-opening {url}")
                        await page.goto(url)
                        try:
                            await page.wait_for_selector(selectors.CONTAINER, timeout=8000)
                        except Exception:
                            return
                        cards = page.locator(selectors.JOB_CARD)
                    continue
                if raw_job is not None:
                    collected += 1
                    yield raw_job

            if count < _PAGE_SIZE:
                return
            start += _PAGE_SIZE
