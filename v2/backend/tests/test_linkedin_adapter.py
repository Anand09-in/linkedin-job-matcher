"""
Unit tests for the LinkedIn adapter — rewritten 2026-09-08 alongside the
switch from a hand-rolled Playwright scraper to v1's proven
`linkedin-jobs-scraper` (Selenium + real Chrome), see adapter.py's module
docstring for why. The library now owns DOM selectors/pagination/extraction
internally, so there's no local extract_job()-style logic left to test
against a fixture page — these tests cover what's still ours: date/link
parsing, filter-dict -> Query mapping, and the local-only credential check.

Requires the `linkedin-jobs-scraper`/selenium/webdriver-manager deps, which
only the `worker` image installs (kept out of `api` deliberately — see
requirements-worker.txt). Run with:

    docker compose run --rm --no-deps worker pytest tests/test_linkedin_adapter.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from linkedin_jobs_scraper.filters import ExperienceLevelFilters, RelevanceFilters, TimeFilters, TypeFilters

from app.scrapers.base import ScrapeConfig
from app.scrapers.linkedin.adapter import LinkedInScraper, _build_query, _canonicalize_link, _parse_relative_time


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
    identical job, different trk=/refId=/trackingId= query strings. Deduping
    on the raw href would silently treat these as two jobs."""
    a = _canonicalize_link("https://www.linkedin.com/jobs/view/4461227405/?trk=flagship3_search_srp_jobs")
    b = _canonicalize_link(
        "https://www.linkedin.com/jobs/view/4461227405/"
        "?eBP=NOT_ELIGIBLE_FOR_CHARGING&refId=abc123&trackingId=xyz789&trk=flagship3_search_srp_jobs"
    )
    assert a == b == "https://www.linkedin.com/jobs/view/4461227405/"


def test_build_query_maps_filters_and_locations():
    config = ScrapeConfig(
        query="AI Engineer",
        locations=["Bangalore, India", "Remote"],
        filters={
            "relevance": "RECENT",
            "time": "WEEK",
            "type": ["FULL_TIME"],
            "experience": ["ENTRY_LEVEL", "ASSOCIATE"],
        },
        limit=30,
    )
    query = _build_query(config)

    assert query.query == "AI Engineer"
    assert query.options.locations == ["Bangalore, India", "Remote"]
    assert query.options.limit == 30
    assert query.options.skip_promoted_jobs is True
    assert query.options.filters.relevance == RelevanceFilters.RECENT
    assert query.options.filters.time == TimeFilters.WEEK
    assert query.options.filters.type == [TypeFilters.FULL_TIME]
    assert query.options.filters.experience == [ExperienceLevelFilters.ENTRY_LEVEL, ExperienceLevelFilters.ASSOCIATE]


def test_build_query_ignores_unknown_filter_values():
    """A typo'd filter value degrades to 'no filter' rather than raising —
    a single pipeline's misconfiguration shouldn't take down its scrape run."""
    config = ScrapeConfig(query="X", locations=[], filters={"time": "DECADE"}, limit=10)
    query = _build_query(config)
    assert query.options.filters.time == TimeFilters.MONTH  # falls back to the documented default


def test_build_query_defaults_to_no_type_or_experience_filter():
    config = ScrapeConfig(query="X", locations=[], filters={}, limit=10)
    query = _build_query(config)
    assert not query.options.filters.type
    assert not query.options.filters.experience


# ── check_credential (local DB lookup, unrelated to the scraping engine) ────
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


async def test_check_credential_is_a_local_lookup_not_a_live_linkedin_hit(repo, db_session):
    """Real bug, found live: an earlier version of this made an actual live
    call to LinkedIn on every single scrape run (doubling every run's
    footprint, which measurably increased how often a real account got
    logged out — see check_credential's docstring). A later "test cookie"
    feature reintroduced a different live hit on every Settings save and was
    also removed for the same reason. It must be a pure local check: cookie
    configured -> ok, nothing configured -> blocked — never a live call."""
    scraper = LinkedInScraper()

    with patch("app.domain.db.AsyncSessionLocal", return_value=_SessionCtx(db_session)):
        await repo.set_scraper_credential("linkedin", "some-cookie")
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
