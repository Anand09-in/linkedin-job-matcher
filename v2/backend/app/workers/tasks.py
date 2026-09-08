"""
arq task functions.

Phase 0: ping_task proves worker -> Redis -> Postgres wiring end to end.
Phase 3: run_scrape_task runs the real single-step pipeline (scrape ->
extract+match -> filter -> save) via services/scrape_service.py. It replaces
Phase 2's run_scrape_preview_task, which only proved raw-batch wiring against
a throwaway table — real Job rows are now the actual output.
Phase 4: salary_lookup_task — enqueued by run_scrape_pipeline immediately
after each job is saved (FR-5.1), fire-and-forget, never blocks scraping.
"""
from __future__ import annotations

import uuid
from typing import Optional

from loguru import logger

from app.core.llm import get_llm
from app.domain.db import AsyncSessionLocal
from app.domain.models import Job, Pipeline, SystemPing
from app.domain.repository import Repository
from app.services.salary_service import get_salary_benchmark
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

        result = await run_scrape_pipeline(repo, pipeline, limit=limit, arq_redis=ctx["redis"])
        logger.info(
            f"[run_scrape_task] pipeline={pipeline.name} status={result['status']} "
            f"seen={result['jobs_seen']} saved={result['jobs_saved']} rejected={result['jobs_rejected']}"
        )
        return {**result, "run_id": str(result["run_id"])}


async def salary_lookup_task(ctx, job_id: str) -> dict:
    """
    FR-5: web search + LLM synthesis for one job's salary estimate.
    Idempotent by job_id (FR-5.4) — safe to run twice, just overwrites
    salary_benchmark with the same or refreshed data. A failure here never
    touches the job's match_score/status/visibility (FR-5.3) — only its
    salary_benchmark/salary_enrichment_status fields.
    """
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        job = await session.get(Job, uuid.UUID(job_id))
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        try:
            llm = get_llm()
            benchmark = await get_salary_benchmark(
                job_title=job.title,
                company=job.company,
                location=job.location,
                experience_years_min=job.experience_years_min,
                llm=llm,
            )
            await repo.update_job_salary_benchmark(job.id, benchmark.model_dump(), status="done")
            logger.info(f"[salary_lookup_task] job={job.id} confidence={benchmark.confidence}")
            return {"job_id": job_id, "status": "done", "confidence": benchmark.confidence}
        except Exception as e:
            logger.error(f"[salary_lookup_task] failed for job={job.id}: {e}")
            await repo.update_job_salary_benchmark(job.id, {}, status="failed")
            return {"job_id": job_id, "status": "failed", "error": str(e)}
