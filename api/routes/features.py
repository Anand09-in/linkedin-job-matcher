"""
Feature endpoints — cover letter, ATS score, interview prep, etc.

Phase 6 implementation.
"""
from __future__ import annotations
from fastapi import APIRouter

router = APIRouter(prefix="/features", tags=["features"])


@router.post("/cover-letter/{job_id}")
async def generate_cover_letter(job_id: str, resume_id: str):
    """Generate a tailored cover letter. TODO Phase 6."""
    raise NotImplementedError("Phase 6")


@router.get("/ats-score/{job_id}")
async def get_ats_score(job_id: str, resume_id: str):
    """Return ATS keyword match score. TODO Phase 6."""
    raise NotImplementedError("Phase 6")


@router.get("/skill-gaps")
async def get_skill_gaps(resume_id: str):
    """Return aggregated skill gaps across all jobs. TODO Phase 6."""
    raise NotImplementedError("Phase 6")


@router.post("/interview-prep/{job_id}")
async def generate_interview_questions(job_id: str, resume_id: str):
    """Generate interview questions for a specific job. TODO Phase 6."""
    raise NotImplementedError("Phase 6")


@router.get("/company-research/{job_id}")
async def get_company_research(job_id: str):
    """Return company research summary. TODO Phase 6."""
    raise NotImplementedError("Phase 6")
