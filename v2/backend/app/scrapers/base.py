"""
BaseScraper interface — FR-1 (universal scraper framework).

Adapters take a plain ScrapeConfig, not the Pipeline ORM model architecture.md
originally sketched — this is a deliberate refinement made during Phase 2
implementation: an adapter that depends on SQLAlchemy/async sessions can't be
fixture-tested in isolation (system-design.md §6), and there's no reason a
scraper needs anything about a Pipeline beyond its query/locations/filters/
batch_size. services/scrape_service.py (Phase 3) builds a ScrapeConfig from a
real Pipeline row before calling the adapter.

FR-1.3: adding a new site MUST NOT require changes here — checked mechanically,
not just assumed, in tests/test_scraper_framework.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator, Protocol, TypeVar

from pydantic import BaseModel, Field


class ScrapeConfig(BaseModel):
    query: str
    locations: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)
    batch_size: int = 5
    limit: int = 50


class RawJob(BaseModel):
    title: str
    company: str
    location: str | None = None
    link: str
    apply_link: str | None = None
    description: str = ""
    # Both the site's raw string and our best-effort parse of it — mirrors the
    # v1 bug this exists to avoid repeating: v1 only kept the parsed value and
    # it silently ended up empty for every job with no way to tell why.
    date_posted_raw: str | None = None
    date_posted: datetime | None = None
    # Sponsored/ad listings on some sites carry no posted-date at all, unlike
    # organic postings — surfaced explicitly so a missing date_posted reads
    # as "this is a promoted listing, expected" rather than looking like an
    # extraction failure.
    is_promoted: bool = False


class BaseScraper(Protocol):
    site_name: str

    def scrape(self, config: ScrapeConfig) -> AsyncIterator[list[RawJob]]:
        """Yields batches of up to config.batch_size RawJob (last batch may be smaller)."""
        ...


_T = TypeVar("_T")


async def batched(items: AsyncIterator[_T], size: int) -> AsyncIterator[list[_T]]:
    """Shared batching helper (FR-1.4) — lives here, not in any one adapter,
    so every adapter gets identical batch-yielding behavior for free."""
    batch: list[_T] = []
    async for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
