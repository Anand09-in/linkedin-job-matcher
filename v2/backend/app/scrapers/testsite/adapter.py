"""
A trivial, network-free second adapter — exists ONLY to prove FR-1.3
("adding a new site adapter MUST NOT require changes to base.py/registry.py")
mechanically rather than by assertion. See tests/test_scraper_framework.py.

Not a real site: generates canned RawJob rows in memory. If you're reading
this looking for a template for a real second adapter (Indeed, Naukri, ...),
this shows the minimum shape but skips everything a real adapter needs
(network calls, selectors, session handling) — see linkedin/adapter.py for that.
"""
from __future__ import annotations

from typing import AsyncIterator

from app.scrapers.base import RawJob, ScrapeConfig, batched
from app.scrapers.registry import register


async def _generate_jobs(config: ScrapeConfig) -> AsyncIterator[RawJob]:
    for i in range(config.limit):
        yield RawJob(
            title=f"{config.query} #{i}",
            company="Testsite Inc.",
            location=config.locations[0] if config.locations else None,
            link=f"https://testsite.example/jobs/{i}",
            description=f"A fake posting for '{config.query}', number {i}.",
        )


@register("testsite")
class TestSiteScraper:
    site_name = "testsite"

    async def scrape(self, config: ScrapeConfig) -> AsyncIterator[list[RawJob]]:
        async for batch in batched(_generate_jobs(config), config.batch_size):
            yield batch
