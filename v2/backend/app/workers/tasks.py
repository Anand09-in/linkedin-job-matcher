"""
arq task functions.

Phase 0: ping_task proves worker -> Redis -> Postgres wiring end to end.
Phase 2: run_scrape_preview_task proves worker -> Playwright/site -> Redis ->
Postgres wiring, without touching the real Job table (extraction/filtering
that decides what becomes a Job is Phase 3's job, not this one).
Phase 3/4 add the real run_scrape_task and salary_lookup_task here.
"""
from __future__ import annotations

import uuid

from loguru import logger

from app.domain.db import AsyncSessionLocal
from app.domain.models import Pipeline, ScrapeDebugBatch, SystemPing
from app.scrapers.base import ScrapeConfig
from app.scrapers.registry import get_scraper


async def ping_task(ctx, message: str = "pong") -> dict:
    """Writes a SystemPing row to Postgres and returns its id — the arq result
    (visible via `await redis.get(job.job_id ...)` / arq's result store) plus
    the DB row are the two independent ways to confirm this ran."""
    async with AsyncSessionLocal() as session:
        ping = SystemPing(message=message)
        session.add(ping)
        await session.commit()
        await session.refresh(ping)
        logger.info(f"[ping_task] wrote SystemPing id={ping.id} message={message!r}")
        return {"id": ping.id, "message": ping.message}


async def run_scrape_preview_task(ctx, pipeline_id: str, limit: int = 50) -> dict:
    """
    Phase 2 exit criteria: run a real adapter against a real Pipeline and
    prove correct batches of `pipeline.batch_size` come out, each landing in
    Postgres as a ScrapeDebugBatch row — no Job rows involved (Phase 3).

    `limit` defaults to ScrapeConfig's own default (50) but is overridable so
    manual live-LinkedIn test runs can request a small number of jobs instead
    of always pulling the full default — deliberately going easy on rate
    limits after Phase 2 testing showed LinkedIn throttling results after a
    few rapid-fire runs on one session.
    """
    async with AsyncSessionLocal() as session:
        pipeline = await session.get(Pipeline, uuid.UUID(pipeline_id))
        if pipeline is None:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        config = ScrapeConfig(
            query=pipeline.query,
            locations=pipeline.locations,
            filters=pipeline.filters,
            batch_size=pipeline.batch_size,
            limit=limit,
        )
        scraper = get_scraper(pipeline.site)

        batch_index = 0
        total_jobs = 0
        async for batch in scraper.scrape(config):
            debug_batch = ScrapeDebugBatch(
                pipeline_id=pipeline.id,
                batch_index=batch_index,
                jobs=[job.model_dump(mode="json") for job in batch],
            )
            session.add(debug_batch)
            await session.commit()
            logger.info(f"[run_scrape_preview_task] pipeline={pipeline.name} batch={batch_index} size={len(batch)}")
            batch_index += 1
            total_jobs += len(batch)

        return {"pipeline_id": pipeline_id, "batches": batch_index, "total_jobs": total_jobs}
