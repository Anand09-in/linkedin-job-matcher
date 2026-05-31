"""
Feature routes — Phase 6 stubs, some with Phase 4 partial implementations.

POST /features/cover-letter/{job_id}   — generate tailored cover letter
GET  /features/ats-score/{job_id}      — ATS keyword match score
GET  /features/skill-gaps              — aggregated skill gaps from DB scores
POST /features/interview-prep/{job_id} — generate interview questions
GET  /features/company-research/{job_id} — company summary

Phase 6 full implementation. Phase 4: skill-gaps endpoint is live.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api.dependencies import get_repo
from db.repository import AsyncJobRepository

router = APIRouter(prefix="/features", tags=["Features"])


@router.get("/skill-gaps")
async def get_skill_gaps(
    limit: int = Query(20, ge=1, le=50, description="Max skill gaps to return"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Aggregate missing skills across all matched jobs.

    Reads missing_skills from all Job rows that have been matched,
    counts frequency, returns sorted list.

    This is a live Phase 4 endpoint — no LLM call needed.
    """
    from sqlalchemy import select
    from db.models import Job
    from collections import Counter

    result = await repo._s.execute(
        select(Job.missing_skills, Job.match_score)
        .where(Job.missing_skills.isnot(None))
        .where(Job.match_score.isnot(None))
    )
    rows = result.all()

    if not rows:
        return {"skill_gaps": [], "total_jobs_analysed": 0}

    all_missing: list[str] = []
    for missing_skills, _ in rows:
        if isinstance(missing_skills, list):
            all_missing.extend(missing_skills)

    counts = Counter(all_missing)
    total_jobs = len(rows)

    gaps = [
        {
            "skill": skill,
            "frequency": count,
            "pct_jobs": round(count / total_jobs, 3),
        }
        for skill, count in counts.most_common(limit)
    ]

    return {
        "skill_gaps": gaps,
        "total_jobs_analysed": total_jobs,
    }


@router.post("/cover-letter/{job_id}")
async def generate_cover_letter(
    job_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Generate a tailored cover letter for a job. Phase 6."""
    raise HTTPException(status_code=501, detail="Cover letter generation coming in Phase 6.")


@router.get("/ats-score/{job_id}")
async def get_ats_score(
    job_id: str,
    resume_id: str = Query(..., description="Resume ID to score against"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Return ATS keyword match score for a job. Phase 6."""
    raise HTTPException(status_code=501, detail="ATS scoring coming in Phase 6.")


@router.post("/interview-prep/{job_id}")
async def generate_interview_questions(
    job_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Generate role-specific interview questions. Phase 6."""
    raise HTTPException(status_code=501, detail="Interview prep coming in Phase 6.")


@router.get("/company-research/{job_id}")
async def get_company_research(
    job_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Return company research summary. Phase 6."""
    raise HTTPException(status_code=501, detail="Company research coming in Phase 6.")
