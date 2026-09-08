"""
Fixture-based tests for the LinkedIn adapter — system-design.md §6: "tested
against recorded HTML fixtures, not live LinkedIn." These exercise the real
extract_job() production code path against a saved page, not a
reimplementation of it.

Requires Playwright + Chromium, which only the `worker` image has (kept out
of `api` deliberately — see requirements-worker.txt). Run with:

    docker compose run --rm --no-deps worker pytest tests/test_linkedin_adapter.py -v
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from playwright.async_api import async_playwright

from datetime import datetime, timedelta, timezone

from app.scrapers.linkedin import selectors
from app.scrapers.linkedin.adapter import LinkedInScraper, _canonicalize_link, _parse_relative_time, extract_job
from app.scrapers.linkedin.url_builder import build_search_url

FIXTURE = Path(__file__).parent / "fixtures" / "linkedin_search_page.html"


@pytest.fixture
async def fixture_page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(f"file://{FIXTURE}")
        yield page
        await browser.close()


async def test_extract_job_reads_title_company_location_date(fixture_page):
    card = fixture_page.locator(selectors.JOB_CARD).nth(0)
    job = await extract_job(fixture_page, card)

    assert job is not None
    assert job.title == "Machine Learning Engineer"
    assert job.company == "Acme Corp"
    assert job.location == "Bangalore, India"
    assert job.link.endswith("/jobs/view/1111")
    assert job.date_posted_raw == "2026-08-20T00:00:00.000Z"
    assert job.date_posted is not None
    assert (job.date_posted.year, job.date_posted.month, job.date_posted.day) == (2026, 8, 20)


async def test_extract_job_clicks_through_to_swapped_description_per_job(fixture_page):
    """The part a purely static fixture couldn't prove: the adapter must
    click each job's link and read the panel AFTER it swaps, and must get
    the right content for each distinct job, not just whatever was already
    on the page."""
    card0 = fixture_page.locator(selectors.JOB_CARD).nth(0)
    job0 = await extract_job(fixture_page, card0)
    assert job0.description == "Build and ship ML models at scale."

    card1 = fixture_page.locator(selectors.JOB_CARD).nth(1)
    job1 = await extract_job(fixture_page, card1)
    assert job1.description == "Own our data pipelines end to end."


async def test_extract_job_handles_missing_date_posted_gracefully(fixture_page):
    """The fixture's third card has no <time> element at all — this is
    exactly the class of failure that silently broke v1 (date_posted ended
    up empty for every one of 324 jobs, with no way to tell why from the
    data alone). Here it must come back as an explicit None, not '', and
    extraction of every other field must still succeed."""
    card2 = fixture_page.locator(selectors.JOB_CARD).nth(2)
    job2 = await extract_job(fixture_page, card2)

    assert job2 is not None
    assert job2.title == "Backend Engineer"
    assert job2.date_posted_raw is None
    assert job2.date_posted is None


async def test_extract_job_falls_back_to_relative_time_text(fixture_page):
    """The fixture's fourth card has a <time> element with NO datetime
    attribute, only visible text ("1 week ago") — this is what the user
    reported seeing on real LinkedIn, and it's a different failure mode than
    the third card's "no <time> element at all": here the element exists,
    but there's nothing machine-readable on it, so the adapter must fall
    back to the human-readable text rather than giving up."""
    card3 = fixture_page.locator(selectors.JOB_CARD).nth(3)
    job3 = await extract_job(fixture_page, card3)

    assert job3 is not None
    assert job3.title == "Platform Engineer"
    assert job3.date_posted_raw == "1 week ago"
    assert job3.date_posted is not None
    # Approximate by design (see _parse_relative_time's docstring) — just
    # confirm it landed within a few seconds of "7 days before now", not an
    # exact instant.
    expected = datetime.now(timezone.utc) - timedelta(weeks=1)
    assert abs((job3.date_posted - expected).total_seconds()) < 10


async def test_extract_job_detects_promoted_listing_with_no_date(fixture_page):
    """The fixture's fifth card reproduces exactly what a real live scrape
    showed during Phase 2 testing: a batch of jobs that ALL came back with
    date_posted=None, which turned out to be because they were promoted/
    sponsored listings — those carry no date at all, unlike organic postings.
    is_promoted=True turns that from "looks like a bug" into "expected"."""
    card4 = fixture_page.locator(selectors.JOB_CARD).nth(4)
    job4 = await extract_job(fixture_page, card4)

    assert job4 is not None
    assert job4.title == "Cloud Engineer"
    assert job4.is_promoted is True
    assert job4.date_posted_raw is None
    assert job4.date_posted is None


async def test_extract_job_non_promoted_listing_is_flagged_false(fixture_page):
    """Every other fixture card lacks a 'Promoted' <li> — confirms the
    detection doesn't false-positive on ordinary cards."""
    card0 = fixture_page.locator(selectors.JOB_CARD).nth(0)
    job0 = await extract_job(fixture_page, card0)
    assert job0.is_promoted is False


def test_parse_relative_time_handles_common_linkedin_formats():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)

    assert _parse_relative_time("Just now", now=now) == now
    assert _parse_relative_time("Today", now=now) == now
    assert _parse_relative_time("Yesterday", now=now).date() == datetime(2026, 9, 7).date()
    assert _parse_relative_time("1 day ago", now=now).date() == datetime(2026, 9, 7).date()
    assert _parse_relative_time("5 hours ago", now=now) == now - timedelta(hours=5)
    assert _parse_relative_time("30 minutes ago", now=now) == now - timedelta(minutes=30)
    assert _parse_relative_time("3 weeks ago", now=now) == now - timedelta(weeks=3)
    assert _parse_relative_time("2mo", now=now) == now - timedelta(days=60)
    assert _parse_relative_time("1yr", now=now) == now - timedelta(days=365)
    assert _parse_relative_time("2d", now=now) == now - timedelta(days=2)
    assert _parse_relative_time("", now=now) is None
    assert _parse_relative_time("some nonsense", now=now) is None


def test_canonicalize_link_strips_tracking_query_params():
    """The same job posting, seen in two different search-result contexts —
    reproduces exactly what came back from a real live scrape during Phase 2
    testing: identical job, different trk=/refId=/trackingId= query strings.
    Deduping on the raw href would have silently treated these as two jobs."""
    a = _canonicalize_link("https://www.linkedin.com/jobs/view/4461227405/?trk=flagship3_search_srp_jobs")
    b = _canonicalize_link(
        "https://www.linkedin.com/jobs/view/4461227405/"
        "?eBP=NOT_ELIGIBLE_FOR_CHARGING&refId=abc123&trackingId=xyz789&trk=flagship3_search_srp_jobs"
    )
    assert a == b == "https://www.linkedin.com/jobs/view/4461227405/"


def test_build_search_url_maps_filters_to_linkedin_query_params():
    url = build_search_url(
        query="AI Engineer",
        location="Bangalore, India",
        filters={
            "relevance": "RECENT",
            "time": "WEEK",
            "type": ["FULL_TIME"],
            "experience": ["ENTRY_LEVEL", "ASSOCIATE"],
        },
        start=25,
    )
    assert "keywords=AI+Engineer" in url
    assert "location=Bangalore" in url
    assert "sortBy=DD" in url
    assert "f_TPR=r604800" in url
    assert "f_JT=F" in url
    assert "f_E=2%2C3" in url
    assert "start=25" in url


def test_build_search_url_ignores_unknown_filter_values():
    """A typo'd filter value degrades to 'no filter' rather than raising —
    a single pipeline's misconfiguration shouldn't take down its scrape run."""
    url = build_search_url("X", "", {"time": "DECADE"}, start=0)
    assert "f_TPR" not in url


# ── check_credential (real, live account-safety fix) ─────────────────────────
#
# check_credential() (and the _resolve_li_at_cookie() it calls) open their
# own `async with AsyncSessionLocal() as session:` internally — same
# lazy-import-respects-source-patch pattern as core/llm.py's
# _get_active_llm_setting(), so these tests patch app.domain.db's
# AsyncSessionLocal the same way test_api_routes.py's api_client fixture
# does, reusing the SAME open `db_session`/`repo` transaction rather than a
# second real connection possibly bound to the dev database.


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


async def test_check_credential_is_a_local_db_lookup_not_a_live_linkedin_hit(repo, db_session, monkeypatch):
    """Real bug, found live: this used to make an actual Playwright call to
    LinkedIn on every single scrape run (doubling every run's footprint,
    which measurably increased how often a real account got logged out —
    see check_credential's docstring). It must now be a pure DB lookup: no
    live check_cookie_valid() call reachable, regardless of what's in the DB."""
    monkeypatch.setattr(
        "app.scrapers.linkedin.cookie_check.check_cookie_valid",
        lambda cookie: (_ for _ in ()).throw(AssertionError("check_credential must not call check_cookie_valid live")),
    )
    scraper = LinkedInScraper()
    await repo.set_scraper_credential("linkedin", "some-cookie")

    with patch("app.domain.db.AsyncSessionLocal", return_value=_SessionCtx(db_session)):
        # Never checked yet -> not blocked (only a KNOWN-invalid result blocks a run).
        ok, _ = await scraper.check_credential()
        assert ok is True

        await repo.record_scraper_credential_check("linkedin", "invalid")
        ok, message = await scraper.check_credential()
        assert ok is False
        assert "invalid" in message.lower()

        await repo.record_scraper_credential_check("linkedin", "valid")
        ok, _ = await scraper.check_credential()
        assert ok is True


async def test_check_credential_fails_with_no_cookie_configured_anywhere(repo, db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "li_at_cookie", "")

    with patch("app.domain.db.AsyncSessionLocal", return_value=_SessionCtx(db_session)):
        scraper = LinkedInScraper()
        ok, message = await scraper.check_credential()
    assert ok is False
    assert "no linkedin session cookie" in message.lower()
