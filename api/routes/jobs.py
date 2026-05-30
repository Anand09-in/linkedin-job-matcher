"""
GET  /jobs       — list jobs with filters & pagination
GET  /jobs/{id}  — single job detail
PATCH /jobs/{id} — update status (tracker)

Phase 4 implementation.
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import JobResponse, StatusUpdateRequest
from db.database import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/", response_model=list[JobResponse])
async def list_jobs(
    min_score: Optional[float] = Query(None, ge=0, le=1),
    status: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    """List jobs with optional filters. TODO Phase 4."""
    raise NotImplementedError("Phase 4")


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single job by ID. TODO Phase 4."""
    raise NotImplementedError("Phase 4")


@router.patch("/{job_id}/status")
async def update_job_status(
    job_id: str,
    body: StatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update application tracking status. TODO Phase 4."""
    raise NotImplementedError("Phase 4")
