"""
Scrape routes (Phase 7, architecture.md §3.4) — replaces main.py's
`/debug/scrape`, `/debug/scrape-runs` prototyping endpoints. Triggering is
still fire-and-forget via arq (`run_scrape_task`, unchanged since Phase 3) —
this module only adds the real, documented HTTP surface around it.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_repo
from app.api.models import ScrapeRunResponse, ScrapeTriggerRequest, ScrapeTriggerResponse
from app.domain.repository import Repository

router = APIRouter(prefix="/scrape", tags=["Scrape"])


@router.post("", response_model=ScrapeTriggerResponse, status_code=202)
async def trigger_scrape(body: ScrapeTriggerRequest, request: Request, repo: Repository = Depends(get_repo)):
    """
    Enqueues run_scrape_task for one pipeline — 202 Accepted with a job_id;
    poll GET /scrape/runs?pipeline_id= for progress (FR-1A.6). Triggering
    works regardless of the pipeline's `enabled` flag — that flag only gates
    the (future) scheduler, not a manual trigger.
    """
    pipeline = await repo.get_pipeline(body.pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {body.pipeline_id} not found")

    job = await request.app.state.redis.enqueue_job("run_scrape_task", str(body.pipeline_id), body.limit)
    return ScrapeTriggerResponse(enqueued=True, job_id=job.job_id, pipeline_id=body.pipeline_id)


@router.get("/runs", response_model=list[ScrapeRunResponse])
async def list_scrape_runs(
    pipeline_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    repo: Repository = Depends(get_repo),
):
    runs = await repo.list_scrape_runs(pipeline_id=pipeline_id, limit=limit)
    return [ScrapeRunResponse.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=ScrapeRunResponse)
async def get_scrape_run(run_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    run = await repo.get_scrape_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Scrape run {run_id} not found")
    return ScrapeRunResponse.model_validate(run)


@router.post("/{run_id}/cancel", response_model=ScrapeRunResponse)
async def cancel_scrape_run(run_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    """
    Best-effort, cooperative stop (Pipelines page "Stop" action) — raises
    `cancel_requested`, which the running scrape loop notices between
    batches (scrape_service.py), not instantly. 409 if the run isn't
    currently `running` (already finished — nothing to cancel).
    """
    existing = await repo.get_scrape_run(run_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Scrape run {run_id} not found")
    if existing.status != "running":
        raise HTTPException(status_code=409, detail=f"Scrape run {run_id} is '{existing.status}', not running — nothing to cancel")

    updated = await repo.request_scrape_run_cancellation(run_id)
    return ScrapeRunResponse.model_validate(updated)
