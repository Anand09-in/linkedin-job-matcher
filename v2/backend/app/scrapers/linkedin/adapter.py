"""
LinkedIn scraper adapter — wraps v1's proven `linkedin-jobs-scraper` library
(Selenium + real Chrome) instead of driving Playwright directly.

Real, live incident this rewrite responds to (2026-09-08): a hand-rolled
Playwright adapter — even after adding navigator.webdriver spoofing
(browser.py, now removed) and human-like delays between clicks — got a real
LinkedIn account restricted (LinkedIn's own "unauthorized access or other
activity that doesn't comply with our policies" lockout, requiring ID
verification to recover) within minutes of a 5-job test run. Side-by-side on
a second account: v1's `linkedin-jobs-scraper` scraped 200+ jobs in one run
with zero issues, using the exact config in this repo's root `config.yaml`
(slow_mo=1.5, max_workers=1, page_load_timeout=40, headless=True — real
Chrome via Selenium, not Playwright's bundled Chromium).

This adapter reuses that exact config rather than re-guessing new
anti-detection knobs on top of a custom scraper — the whole point is to stop
being the thing that's different from what's already proven safe. The
library owns DOM selectors, pagination, and card-click pacing internally;
this file's job is just bridging its synchronous, callback-driven API
(`scraper.run()` blocks and fires `Events.DATA` per job) into v2's
`AsyncIterator[list[RawJob]]` contract, and mapping its `EventData` fields
onto `RawJob`.

Trade-off accepted, not silently absorbed: this reintroduces v1's own
`date_posted` unreliability (system-design.md decision log #3's whole reason
for writing a from-scratch Playwright adapter in the first place). Account
safety wins that trade — a wrong/missing posted-date is a data-quality
annoyance; an account lockout is not. `_parse_date`/`_parse_relative_time`
below still run on whatever the library DOES give back, so this only
regresses to "as good as v1", not worse.

Real, live gap found after this rewrite shipped: the Pipelines page "Stop"
action set ScrapeRun.cancel_requested, but the run kept scraping regardless
— clicking Stop had visibly zero effect, still hitting LinkedIn minutes
later. Root cause: `linkedin_jobs_scraper.LinkedinScraper` exposes no
stop()/cancel() API at all (checked its source directly — `run()` just
blocks a ThreadPoolExecutor future with no interrupt hook), and the
webdriver instance it creates per-location is a local variable buried
inside a private method, never exposed to callers. There is no clean,
library-level way to interrupt it. `_iter_jobs` below now runs a watcher
task alongside the scrape that polls ScrapeRun.cancel_requested directly
and, on seeing it, kills the chromedriver/chrome OS processes THIS worker
process spawned (`_kill_browser_descendants`) — blunt, but it is the only
lever that actually exists, and it makes the next Selenium command raise,
which aborts the library's run() promptly instead of letting it finish on
its own.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.config import Config as LJSConfig
from linkedin_jobs_scraper.events import Events, EventData
from linkedin_jobs_scraper.filters import (
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
    RelevanceFilters,
    TimeFilters,
    TypeFilters,
)
from linkedin_jobs_scraper.query import Query, QueryFilters, QueryOptions
from webdriver_manager.chrome import ChromeDriverManager

from app.scrapers.base import RawJob, ScrapeConfig, batched
from app.scrapers.registry import register

# Proven-safe values from this repo's root config.yaml (v1) — see this
# module's docstring for why these aren't re-tuned here.
_SLOW_MO = 1.5
_MAX_WORKERS = 1
_PAGE_LOAD_TIMEOUT = 40

_RELEVANCE = {"RECENT": RelevanceFilters.RECENT, "RELEVANT": RelevanceFilters.RELEVANT}
_TIME = {"DAY": TimeFilters.DAY, "WEEK": TimeFilters.WEEK, "MONTH": TimeFilters.MONTH, "ANY": TimeFilters.ANY}
_TYPE = {
    "FULL_TIME": TypeFilters.FULL_TIME,
    "PART_TIME": TypeFilters.PART_TIME,
    "CONTRACT": TypeFilters.CONTRACT,
    "TEMPORARY": TypeFilters.TEMPORARY,
    "INTERNSHIP": TypeFilters.INTERNSHIP,
}
_EXPERIENCE = {
    "INTERNSHIP": ExperienceLevelFilters.INTERNSHIP,
    "ENTRY_LEVEL": ExperienceLevelFilters.ENTRY_LEVEL,
    "ASSOCIATE": ExperienceLevelFilters.ASSOCIATE,
    "MID_SENIOR": ExperienceLevelFilters.MID_SENIOR,
    "DIRECTOR": ExperienceLevelFilters.DIRECTOR,
    "EXECUTIVE": ExperienceLevelFilters.EXECUTIVE,
}
_REMOTE = {
    "ON_SITE": OnSiteOrRemoteFilters.ON_SITE,
    "REMOTE": OnSiteOrRemoteFilters.REMOTE,
    "HYBRID": OnSiteOrRemoteFilters.HYBRID,
}


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
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
    """Best-effort parse of a human-readable relative time badge ("1 day
    ago", "3w") into an absolute datetime — see RawJob's docstring for why
    date_posted_raw is always kept alongside this best-effort parse."""
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
    unit_word = match.group(2).rstrip("s")
    unit = _RELATIVE_UNIT_ALIASES.get(unit_word)
    if unit is None:
        return None

    if unit == "months":
        return now - timedelta(days=amount * 30)
    if unit == "years":
        return now - timedelta(days=amount * 365)
    return now - timedelta(**{unit: amount})


def _canonicalize_link(url: str) -> str:
    """Strip tracking query params (trk=, trackingId=, refId=, eBP=) so the
    same job seen twice canonicalizes to the same link for dedup — see
    Job.link's unique constraint."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _build_query(config: ScrapeConfig) -> Query:
    f = config.filters or {}
    type_filters = [_TYPE[t] for t in f.get("type", []) if t in _TYPE] or None
    exp_filters = [_EXPERIENCE[e] for e in f.get("experience", []) if e in _EXPERIENCE] or None
    remote_filters = [_REMOTE[r] for r in f.get("on_site_or_remote", []) if r in _REMOTE] or None

    return Query(
        query=config.query,
        options=QueryOptions(
            locations=config.locations or [],
            limit=config.limit,
            apply_link=True,
            skip_promoted_jobs=True,
            filters=QueryFilters(
                relevance=_RELEVANCE.get(f.get("relevance", "RECENT"), RelevanceFilters.RECENT),
                time=_TIME.get(f.get("time", "MONTH"), TimeFilters.MONTH),
                type=type_filters,
                experience=exp_filters,
                on_site_or_remote=remote_filters,
            ),
        ),
    )


def _kill_browser_descendants() -> None:
    """Blunt, OS-level force-stop for a Stop click — see this module's
    docstring for why nothing gentler exists. Only touches chromedriver/
    chrome processes that are actual descendants of THIS worker process
    (never anything else on the machine, including a real Chrome the user
    has open themselves), since Selenium always spawns chromedriver as a
    direct child of the process that created the webdriver."""
    try:
        import psutil
    except ImportError:
        logger.warning("[linkedin] psutil not installed — cannot force-stop the browser on cancel")
        return

    try:
        me = psutil.Process(os.getpid())
    except psutil.NoSuchProcess:
        return

    for child in me.children(recursive=True):
        try:
            if child.name().lower().startswith(("chromedriver", "chrome")):
                child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


_CANCELLED = object()


async def _watch_for_cancellation(run_id: Optional[str], queue: "asyncio.Queue", cancelled: dict) -> None:
    """Runs alongside the scrape, polling ScrapeRun.cancel_requested every 2s
    (own short-lived DB session each time, same lazy-import pattern as
    _resolve_li_at_cookie). On seeing it: flip `cancelled["value"]` FIRST
    (so run_blocking's except-handler, racing this on a different thread,
    is guaranteed to see it regardless of timing), then force-stop the
    browser and push _CANCELLED so _iter_jobs's consumer loop stops
    promptly instead of waiting for whatever's left in the queue (or
    nothing, if the browser was mid-navigation with no job pending)."""
    if not run_id:
        return
    from app.domain.db import AsyncSessionLocal
    from app.domain.repository import Repository
    import uuid as _uuid

    try:
        while True:
            await asyncio.sleep(2)
            async with AsyncSessionLocal() as session:
                run = await Repository(session).get_scrape_run(_uuid.UUID(run_id))
            if run is not None and run.cancel_requested:
                logger.info(f"[linkedin] cancel requested for run={run_id} — force-stopping the browser")
                cancelled["value"] = True
                _kill_browser_descendants()
                await queue.put(_CANCELLED)
                return
    except asyncio.CancelledError:
        return


async def _resolve_li_at_cookie() -> str:
    """DB-first (Phase 8: UI-editable via Settings, no worker restart needed
    to rotate an expired cookie), falling back to the env var. Same
    isolated-import pattern as core/llm.py's _get_active_llm_setting()."""
    from app.core.config import get_settings
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
        Optional hook scrape_service.py calls (via hasattr) BEFORE starting a
        run, as a setup-prerequisite check in the same tier as an
        adapter-connect failure or a resume-parse failure.

        Deliberately a LOCAL check only — NOT a live browser hit against
        LinkedIn (a separate live "is this cookie valid" probe was tried and
        removed: it was extra, unmeasured account activity on top of
        whatever the next real scrape does anyway). Only catches "no cookie
        configured at all" — an actually-bad cookie now surfaces as a real
        failure on the scrape run itself (adapter.py's _Failed sentinel),
        with the real error message, instead of a separate probe.
        """
        cookie = await _resolve_li_at_cookie()
        if not cookie:
            return False, "No LinkedIn session cookie configured — set one via Settings in the UI (or LI_AT_COOKIE in .env)."
        return True, ""

    async def scrape(self, config: ScrapeConfig) -> AsyncIterator[list[RawJob]]:
        cookie = await _resolve_li_at_cookie()
        if not cookie:
            raise ValueError(
                "No LinkedIn session cookie configured — set one via Settings in the UI (or LI_AT_COOKIE in .env)."
            )

        async for batch in batched(self._iter_jobs(cookie, config), config.batch_size):
            yield batch

    async def _iter_jobs(self, cookie: str, config: ScrapeConfig) -> AsyncIterator[RawJob]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()
        seen_links: set[str] = set()

        class _Failed:
            """Distinct from _DONE — found live: a fatal library error (e.g.
            InvalidCookieException) was being logged correctly but then
            masked by pushing _DONE anyway, so the run reported "completed"
            with whatever partial results it had instead of "failed". The
            worker log had the real error; the UI showed a green badge."""

            def __init__(self, message: str) -> None:
                self.message = message

        def _on_data(data: EventData) -> None:
            link = _canonicalize_link(data.link)
            raw_date = data.date or None
            raw = RawJob(
                title=data.title,
                company=data.company,
                location=getattr(data, "place", None) or getattr(data, "location", None),
                link=link,
                apply_link=getattr(data, "apply_link", None),
                description=data.description or "",
                date_posted_raw=raw_date,
                date_posted=_parse_date(raw_date) or (_parse_relative_time(raw_date) if raw_date else None),
            )
            loop.call_soon_threadsafe(queue.put_nowait, raw)

        def _on_error(error) -> None:
            logger.warning(f"[linkedin] scraper error: {error}")

        def _on_end() -> None:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        cancelled = {"value": False}

        def run_blocking() -> None:
            os.environ["LI_AT_COOKIE"] = cookie
            # Config.LI_AT_COOKIE is a class attr read at import time by the
            # library — patch it directly too, same as v1's _set_cookie().
            LJSConfig.LI_AT_COOKIE = cookie

            try:
                scraper = LinkedinScraper(
                    chrome_executable_path=ChromeDriverManager().install(),
                    headless=True,
                    max_workers=_MAX_WORKERS,
                    slow_mo=_SLOW_MO,
                    page_load_timeout=_PAGE_LOAD_TIMEOUT,
                )
                scraper.on(Events.DATA, _on_data)
                scraper.on(Events.ERROR, _on_error)
                scraper.on(Events.END, _on_end)
                scraper.run([_build_query(config)])
            except Exception as e:
                # Also fires when _watch_for_cancellation kills the browser
                # out from under this call — that's expected, not a real
                # failure, so don't push _Failed over a _CANCELLED that may
                # already be on its way (or arrive after): the `cancelled`
                # flag lets the consumer loop tell the two apart regardless
                # of which one it happens to see first.
                if not cancelled["value"]:
                    logger.error(f"[linkedin] scraper fatal error: {e}")
                    loop.call_soon_threadsafe(queue.put_nowait, _Failed(str(e)))

        asyncio.create_task(asyncio.to_thread(run_blocking))
        watcher = asyncio.create_task(_watch_for_cancellation(config.run_id, queue, cancelled))

        try:
            collected = 0
            while True:
                item = await queue.get()
                if item is _DONE:
                    return
                if item is _CANCELLED:
                    cancelled["value"] = True
                    logger.info(f"[linkedin] run={config.run_id} stopped by cancellation")
                    return
                if isinstance(item, _Failed):
                    if cancelled["value"]:
                        return
                    # Propagates up through batched() -> scrape() to
                    # scrape_service.py's run-setup try/except, which marks
                    # the ScrapeRun "failed" and records the message — same
                    # tier as an adapter-connect failure or a resume-parse
                    # failure.
                    raise RuntimeError(item.message)
                if item.link in seen_links:
                    continue
                seen_links.add(item.link)
                collected += 1
                yield item
                if collected >= config.limit:
                    return
        finally:
            watcher.cancel()
