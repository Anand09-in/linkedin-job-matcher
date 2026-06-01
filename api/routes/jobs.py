"""
Job routes.

GET   /jobs              — list jobs with filters & pagination
GET   /jobs/{id}         — single job detail
GET   /jobs/{id}/similar — similar jobs by embedding (Phase 5+)
PATCH /jobs/{id}/status  — update application tracking status

Phase 4.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.dependencies import get_repo
from api.models import JobResponse, StatusUpdateRequest, StatusUpdateResponse
from db.models import Job
from db.repository import AsyncJobRepository

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def _job_to_response(job: Job) -> JobResponse:
    """Convert a SQLAlchemy Job ORM object to a JobResponse Pydantic model."""
    return JobResponse(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        date_posted=job.date_posted,
        link=job.link,
        apply_link=job.apply_link,
        company_link=job.company_link,
        description=job.description,
        insights=job.insights,
        skills_required=job.skills_required,
        skills_nice_to_have=job.skills_nice_to_have,
        experience_years=job.experience_years,
        experience_years_min=job.experience_years_min,
        seniority_level=job.seniority_level,
        employment_type=job.employment_type,
        remote_policy=job.remote_policy,
        salary_range=job.salary_range,
        match_score=job.match_score,
        matched_skills=job.matched_skills,
        missing_skills=job.missing_skills,
        status=job.status,
        scraped_at=job.scraped_at,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    # Match score filters
    min_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Minimum match score"),
    max_score: Optional[float] = Query(None, ge=0.0, le=1.0, description="Maximum match score"),
    # Text filters
    company: Optional[str] = Query(None, description="Filter by company name (partial match)"),
    title: Optional[str] = Query(None, description="Filter by job title (partial match)"),
    location: Optional[str] = Query(None, description="Filter by location (partial match)"),
    # Structured filters
    status: Optional[str] = Query(None, description="Application status: new|saved|applied|interview|offer|rejected"),
    seniority: Optional[str] = Query(None, description="Seniority level: Entry|Junior|Mid|Senior|Lead"),
    remote_policy: Optional[str] = Query(None, description="Remote|Hybrid|On-site"),
    has_description: Optional[bool] = Query(None, description="Only return jobs with a description"),
    has_score: Optional[bool] = Query(None, description="Only return jobs that have been matched"),
    # Pagination
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    # Sorting
    sort_by: str = Query("match_score", description="match_score | scraped_at | company | title | experience"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    List jobs with rich filtering and pagination.

    Results are sorted by match_score descending by default (nulls last).
    """
    from sqlalchemy import select, or_
    from db.models import Job

    q = select(Job)

    # Apply filters
    if min_score is not None:
        q = q.where(Job.match_score >= min_score)
    if max_score is not None:
        q = q.where(Job.match_score <= max_score)
    if company:
        q = q.where(Job.company.ilike(f"%{company}%"))
    if title:
        q = q.where(Job.title.ilike(f"%{title}%"))
    if location:
        q = q.where(Job.location.ilike(f"%{location}%"))
    if status:
        q = q.where(Job.status == status)
    if seniority:
        q = q.where(Job.seniority_level == seniority)
    if remote_policy:
        q = q.where(Job.remote_policy == remote_policy)
    if has_description is True:
        q = q.where(Job.description.isnot(None))
    if has_description is False:
        q = q.where(Job.description.is_(None))
    if has_score is True:
        q = q.where(Job.match_score.isnot(None))
    if has_score is False:
        q = q.where(Job.match_score.is_(None))

    # Apply sorting
    from sqlalchemy import asc, desc, nullslast
    sort_map = {
        "match_score": nullslast(Job.match_score.desc()),
        "scraped_at":  Job.scraped_at.desc(),
        "company":     Job.company.asc(),
        "title":       Job.title.asc(),
        "experience":  nullslast(Job.experience_years_min.asc()),
    }
    order_clause = sort_map.get(sort_by, nullslast(Job.match_score.desc()))
    q = q.order_by(order_clause).limit(limit).offset(offset)

    from db.database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import Depends as _Depends

    # Execute via the repo's session
    result = await repo._s.execute(q)
    jobs = result.scalars().all()

    logger.debug(f"[GET /jobs] filters applied → {len(jobs)} jobs returned")
    return [_job_to_response(j) for j in jobs]


@router.get("/stats", tags=["Jobs"])
async def job_stats(repo: AsyncJobRepository = Depends(get_repo)):
    """
    Return aggregate stats: total jobs, jobs with description, jobs matched, status breakdown.
    """
    from sqlalchemy import select, func
    from db.models import Job

    total_result = await repo._s.execute(select(func.count(Job.id)))
    total = total_result.scalar()

    with_desc = await repo._s.execute(
        select(func.count(Job.id)).where(Job.description.isnot(None))
    )
    with_score = await repo._s.execute(
        select(func.count(Job.id)).where(Job.match_score.isnot(None))
    )
    avg_score = await repo._s.execute(
        select(func.avg(Job.match_score)).where(Job.match_score.isnot(None))
    )

    return {
        "total_jobs": total,
        "with_description": with_desc.scalar(),
        "with_match_score": with_score.scalar(),
        "avg_match_score": round(avg_score.scalar() or 0, 3),
    }


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Get full details for a single job by ID."""
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return _job_to_response(job)


@router.patch("/{job_id}/status", response_model=StatusUpdateResponse)
async def update_job_status(
    job_id: str,
    body: StatusUpdateRequest,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Update the application tracking status of a job.

    Valid transitions: new → saved → applied → interview → offer | rejected
    """
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    updated = await repo.update_job_status(job_id, body.status)
    logger.info(f"[PATCH /jobs/{job_id}/status] → {body.status}")

    return StatusUpdateResponse(
        job_id=job_id,
        status=body.status,
        updated=updated,
    )
