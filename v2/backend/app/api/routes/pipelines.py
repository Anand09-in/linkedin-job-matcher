"""
Pipeline routes (Phase 7, architecture.md §3.4 / FR-1A.1) — replaces
main.py's `/debug/quick-pipeline`. Manages `PIPELINE` rows directly; there
is no separate "activate" step (a pipeline is runnable the moment it
exists — `enabled` only matters to the future scheduler, not manual
POST /scrape triggers).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_repo
from app.api.models import DeletedCountResponse, PipelineCreateRequest, PipelineResponse, PipelineUpdateRequest, RejectedJobResponse
from app.domain.repository import Repository

router = APIRouter(prefix="/pipelines", tags=["Pipelines"])


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(body: PipelineCreateRequest, repo: Repository = Depends(get_repo)):
    if body.resume_id is not None and await repo.get_resume(body.resume_id) is None:
        raise HTTPException(status_code=404, detail=f"Resume {body.resume_id} not found")
    pipeline = await repo.create_pipeline(**body.model_dump())
    return PipelineResponse.model_validate(pipeline)


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(enabled_only: bool = Query(False), repo: Repository = Depends(get_repo)):
    return [PipelineResponse.model_validate(p) for p in await repo.list_pipelines(enabled_only=enabled_only)]


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(pipeline_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    pipeline = await repo.get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    return PipelineResponse.model_validate(pipeline)


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(pipeline_id: uuid.UUID, body: PipelineUpdateRequest, repo: Repository = Depends(get_repo)):
    if await repo.get_pipeline(pipeline_id) is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")

    fields = body.model_dump(exclude_unset=True)
    if "resume_id" in fields and fields["resume_id"] is not None and await repo.get_resume(fields["resume_id"]) is None:
        raise HTTPException(status_code=404, detail=f"Resume {fields['resume_id']} not found")

    updated = await repo.update_pipeline(pipeline_id, **fields)
    return PipelineResponse.model_validate(updated)


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    if await repo.get_pipeline(pipeline_id) is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    await repo.delete_pipeline(pipeline_id)


@router.get("/{pipeline_id}/rejected-jobs", response_model=list[RejectedJobResponse])
async def list_rejected_jobs(
    pipeline_id: uuid.UUID,
    scrape_run_id: Optional[uuid.UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    repo: Repository = Depends(get_repo),
):
    """FR-2.3 audit trail — why jobs didn't pass this pipeline's filter."""
    if await repo.get_pipeline(pipeline_id) is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    rejected = await repo.list_rejected_jobs(pipeline_id=pipeline_id, scrape_run_id=scrape_run_id, limit=limit)
    return [RejectedJobResponse.model_validate(r) for r in rejected]


@router.delete("/{pipeline_id}/scrape-runs", response_model=DeletedCountResponse)
async def clear_scrape_runs(pipeline_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    """Pipelines page "clear run history" action. Never touches a
    currently-`running` run (Repository.delete_scrape_runs) — deletes
    everything else, and the RejectedJob audit rows that belonged to those
    runs go with them (cascade), while jobs those runs saved keep existing,
    just losing their run attribution."""
    if await repo.get_pipeline(pipeline_id) is None:
        raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found")
    deleted = await repo.delete_scrape_runs(pipeline_id)
    return DeletedCountResponse(deleted_count=deleted)
