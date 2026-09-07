"""
arq task functions.

Phase 0: ping_task proves worker -> Redis -> Postgres wiring end to end.
Phase 3: run_scrape_task runs the real single-step pipeline (scrape ->
extract+match -> filter -> save) via services/scrape_service.py. It replaces
Phase 2's run_scrape_preview_task, which only proved raw-batch wiring against
a throwaway table — real Job rows are now the actual output.
Phase 4 adds salary_lookup_task here.
"""
from __future__ import annotations

import uuid
from typing import Optional

from loguru import logger

from app.domain.db import AsyncSessionLocal
from app.domain.models import Pipeline, SystemPing
from app.domain.repository import Repository
from app.services.scrape_service import run_scrape_pipeline


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


async def run_scrape_task(ctx, pipeline_id: str, limit: Optional[int] = None) -> dict:
    """Phase 3 exit criteria: scrape -> extract+match -> filter -> save, all
    in one pass, for one pipeline. See run_scrape_pipeline for the real logic."""
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        pipeline = await session.get(Pipeline, uuid.UUID(pipeline_id))
        if pipeline is None:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        result = await run_scrape_pipeline(repo, pipeline, limit=limit)
        logger.info(
            f"[run_scrape_task] pipeline={pipeline.name} status={result['status']} "
            f"seen={result['jobs_seen']} saved={result['jobs_saved']} rejected={result['jobs_rejected']}"
        )
        return {**result, "run_id": str(result["run_id"])}
