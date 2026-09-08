"""
Job routes (Phase 7, architecture.md §3.4) — replaces main.py's
`/debug/jobs`, `/debug/rejected-jobs` prototyping endpoints with the real,
documented surface. All query-building lives in Repository.list_jobs (Phase
1 design decision — testable without an HTTP layer at all), this module
only translates HTTP <-> Repository calls.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_repo
from app.api.models import (
    BulkDeleteResponse,
    JobCountResponse,
    JobResponse,
    JobStatsResponse,
    JobStatusUpdateRequest,
    JobStatusUpdateResponse,
)
from app.domain.repository import Repository

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    max_score: Optional[float] = Query(None, ge=0.0, le=1.0),
    min_experience: Optional[int] = Query(None, ge=0),
    max_experience: Optional[int] = Query(None, ge=0),
    company: Optional[str] = Query(None, description="Partial match"),
    title: Optional[str] = Query(None, description="Partial match"),
    location: Optional[str] = Query(None, description="Partial match"),
    status: Optional[str] = Query(None, description="new|saved|applied|interview|offer|rejected|deleted"),
    seniority: Optional[str] = Query(None),
    remote_policy: Optional[str] = Query(None),
    has_description: Optional[bool] = Query(None),
    has_score: Optional[bool] = Query(None),
    pipeline_id: Optional[uuid.UUID] = Query(None, description="FR-1A.6: scope results to one pipeline"),
    sort_by: str = Query("match_score", description="Comma-separated: match_score,experience,scraped_at,company,title"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: Repository = Depends(get_repo),
):
    """Deleted jobs are excluded unless status=deleted is explicitly requested."""
    jobs = await repo.list_jobs(
        min_score=min_score, max_score=max_score, min_experience=min_experience, max_experience=max_experience,
        company=company, title=title, location=location, status=status, seniority=seniority,
        remote_policy=remote_policy, has_description=has_description, has_score=has_score,
        pipeline_id=pipeline_id, sort_by=sort_by, limit=limit, offset=offset,
    )
    return [JobResponse.model_validate(j) for j in jobs]


@router.get("/stats", response_model=JobStatsResponse)
async def job_stats(repo: Repository = Depends(get_repo)):
    return JobStatsResponse(**await repo.get_job_stats())


@router.get("/count-before", response_model=JobCountResponse)
async def count_jobs_before(
    before_date: date = Query(..., description="Count jobs on/before this date (YYYY-MM-DD)"),
    repo: Repository = Depends(get_repo),
):
    """Preview how many jobs DELETE /jobs?before_date=... would remove, without deleting anything."""
    count = await repo.count_jobs_before(before_date)
    return JobCountResponse(count=count, before_date=before_date.isoformat())


@router.delete("", response_model=BulkDeleteResponse)
async def delete_jobs_before(
    before_date: date = Query(..., description="Permanently delete jobs posted on/before this date (YYYY-MM-DD)"),
    repo: Repository = Depends(get_repo),
):
    """
    Hard delete (carried over from v1's explicit design: this bulk-cleanup
    action removes rows outright, unlike DELETE /jobs/{id}'s soft delete) —
    cannot be undone.
    """
    deleted = await repo.delete_jobs_before(before_date)
    return BulkDeleteResponse(deleted_count=deleted, before_date=before_date.isoformat())


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobResponse.model_validate(job)


@router.patch("/{job_id}/status", response_model=JobStatusUpdateResponse)
async def update_job_status(job_id: uuid.UUID, body: JobStatusUpdateRequest, repo: Repository = Depends(get_repo)):
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    updated = await repo.update_job_status(job_id, body.status)
    return JobStatusUpdateResponse(job_id=job_id, status=body.status, updated=updated)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    """Soft delete (status="deleted") — carried over from v1: hides the job
    from results but keeps the row so a future scrape of the same link
    doesn't silently resurface it."""
    job = await repo.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    await repo.delete_job(job_id)
