"""
Framework-level tests: the batching contract (FR-1.4) and the FR-1.3 claim
that adding a new site adapter requires zero changes to base.py/registry.py.

FR-1.3's own wording permits "a new adapter module + registry entry" — so the
one place allowed to name a specific site is bootstrap.py (see its
docstring). registry.py and base.py must never need to, which is checked
here mechanically rather than only asserted by design intent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.scrapers.base import RawJob, ScrapeConfig, batched
from app.scrapers.registry import get_scraper, registered_sites


async def _fake_stream(n: int):
    for i in range(n):
        yield i


async def test_batched_groups_items_with_partial_last_batch():
    batches = [b async for b in batched(_fake_stream(12), size=5)]
    assert [len(b) for b in batches] == [5, 5, 2]
    assert [item for b in batches for item in b] == list(range(12))


async def test_batched_empty_stream_yields_nothing():
    batches = [b async for b in batched(_fake_stream(0), size=5)]
    assert batches == []


async def test_two_independent_adapters_are_both_registered_with_no_special_casing():
    """The real cross-adapter proof — bootstrap() pulls in linkedin/adapter.py,
    which needs linkedin-jobs-scraper/selenium. Those are only installed in
    the worker image (requirements-worker.txt), so this test only runs
    meaningfully there; it skips (not fails) in the api image, which
    deliberately doesn't carry that dependency."""
    pytest.importorskip("linkedin_jobs_scraper", reason="linkedin adapter needs linkedin-jobs-scraper — run via the worker image")
    from app.scrapers.bootstrap import bootstrap

    bootstrap()
    assert "linkedin" in registered_sites()
    assert "testsite" in registered_sites()


async def test_testsite_adapter_yields_correctly_sized_batches():
    """testsite/adapter.py is a trivial, network-free second adapter — its
    only purpose is proving the framework generalizes beyond a single site.
    Imported directly (not via bootstrap()) so this test needs nothing
    beyond what the api image already has."""
    import app.scrapers.testsite.adapter  # noqa: F401 — registers "testsite" on import

    scraper = get_scraper("testsite")
    config = ScrapeConfig(query="AI Engineer", locations=["Remote"], batch_size=3, limit=7)

    batches = [b async for b in scraper.scrape(config)]
    assert [len(b) for b in batches] == [3, 3, 1]
    assert all(isinstance(job, RawJob) for batch in batches for job in batch)
    assert batches[0][0].title == "AI Engineer #0"


def test_base_and_registry_name_no_specific_site():
    """base.py and registry.py are pure interface/mechanism — if this test
    ever needs updating to tolerate a site name here, that's FR-1.3 being
    violated, not a fixture going stale."""
    backend_root = Path(__file__).resolve().parent.parent
    for filename in ("app/scrapers/base.py", "app/scrapers/registry.py"):
        text = (backend_root / filename).read_text().lower()
        assert "linkedin" not in text, f"{filename} names a specific site — violates FR-1.3"
        assert "testsite" not in text, f"{filename} names a specific site — violates FR-1.3"
