"""
Feature routes — Phase 6 full implementation.

GET  /features/skill-gaps                   aggregated skill gaps from DB
POST /features/cover-letter/{job_id}        tailored cover letter
GET  /features/ats-score/{job_id}           ATS keyword match (no LLM)
POST /features/interview-prep/{job_id}      12 interview questions + tips
GET  /features/company-research/{job_id}    company research summary
GET  /features/salary-benchmark/{job_id}    salary extraction + market range
GET  /features/tracker-stats                application funnel statistics
POST /features/career-path                  3-horizon career plan + learning roadmap
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select

from api.dependencies import get_repo
from api.models import (
    ATSResponse,
    CareerPathResponse,
    CompanyIntelResponse,
    CompanyResearchResponse,
    CoverLetterResponse,
    InterviewPrepResponse,
    ResumeImprovementResponse,
    SalaryBenchmarkResponse,
    TrackerStatsResponse,
)
from db.models import Job, Resume
from db.repository import AsyncJobRepository

router = APIRouter(prefix="/features", tags=["Features"])

# Keys required per provider (checked before calling LLM to give a clear 400)
_PROVIDER_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "groq":      "GROQ_API_KEY",
    "gemini":    "GOOGLE_API_KEY",
}


def _check_provider_credentials(provider: str | None) -> None:
    """Raise HTTP 400 before the LLM call if required credentials are missing."""
    if not provider or provider == "bedrock" or provider == "ollama":
        return   # bedrock uses boto3 (AWS env vars checked elsewhere); ollama needs no key
    key_name = _PROVIDER_KEY_MAP.get(provider.lower())
    if not key_name:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Valid: anthropic | openai | groq | gemini | bedrock | ollama",
        )
    import os
    from config.settings import get_settings
    settings = get_settings()
    # Check settings attribute first, then raw env var
    attr = key_name.lower()   # e.g. "anthropic_api_key"
    val = getattr(settings, attr, None) or os.getenv(key_name, "")
    if not val or not val.strip():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider '{provider}' requires {key_name} in your .env file. "
                f"Either add the key or choose a provider you already have configured "
                f"(your .env has: bedrock, groq, gemini)."
            ),
        )


# ── Shared helpers ────────────────────────────────────────────────────────────

async def _get_job_or_404(job_id: str, repo: AsyncJobRepository) -> Job:
    job = await repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


async def _get_resume_or_404(
    repo: AsyncJobRepository,
    resume_id: str | None = None,
) -> Resume:
    if resume_id:
        result = await repo._s.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one_or_none()
    else:
        resume = await repo.get_active_resume()
    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No resume found. Upload one via POST /resume.",
        )
    if not resume.parsed_profile:
        raise HTTPException(
            status_code=422,
            detail="Resume not yet parsed. Call POST /resume/{id}/parse first.",
        )
    return resume


def _profile_with_id(resume: Resume) -> dict:
    """Return parsed_profile with resume_id injected."""
    profile = dict(resume.parsed_profile or {})
    profile["resume_id"] = resume.id
    return profile


# ── Skill Gaps ────────────────────────────────────────────────────────────────

@router.get("/skill-gaps")
async def get_skill_gaps(
    limit: int = Query(20, ge=1, le=50),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Aggregate missing skills across all matched jobs, ranked by frequency."""
    result = await repo._s.execute(
        select(Job.missing_skills, Job.matched_skills, Job.match_score)
        .where(Job.missing_skills.isnot(None))
        .where(Job.match_score.isnot(None))
    )
    rows = result.all()

    if not rows:
        return {"skill_gaps": [], "total_jobs_analysed": 0, "your_strengths": [], "top_gap_areas": []}

    scored_jobs = [
        {"missing_skills": r.missing_skills, "matched_skills": r.matched_skills}
        for r in rows
    ]
    from features.skill_gap import analyse_skill_gaps
    analysis = analyse_skill_gaps(scored_jobs, candidate_profile={}, limit=limit)

    return {
        "skill_gaps": [g.model_dump() for g in analysis.skill_gaps],
        "total_jobs_analysed": analysis.total_jobs_analysed,
        "your_strengths": analysis.your_strengths,
        "top_gap_areas": analysis.top_gap_areas,
    }


# ── Cover Letter ──────────────────────────────────────────────────────────────

@router.post("/cover-letter/{job_id}", response_model=CoverLetterResponse)
async def generate_cover_letter(
    job_id: str,
    tone: str = Query("professional", description="professional | confident | friendly"),
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model for this request"),
    provider: str | None = Query(None, description="Override LLM provider for this request"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Generate a cliché-free 3-paragraph cover letter. Cached in-memory per job."""
    _check_provider_credentials(provider)
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    try:
        from features.cover_letter import generate_cover_letter as _gen
        result = _gen(job.to_dict(), _profile_with_id(resume), tone=tone,
                      model_override=model, provider_override=provider)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[CoverLetter] job={job_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return CoverLetterResponse(**result.model_dump())


# ── ATS Scorer ────────────────────────────────────────────────────────────────

@router.get("/ats-score/{job_id}", response_model=ATSResponse)
async def get_ats_score(
    job_id: str,
    resume_id: str | None = Query(None),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """4-component ATS score: keyword density, title words, sections, quantified achievements."""
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    from features.ats_scorer import score_ats
    result = score_ats(job.to_dict(), _profile_with_id(resume), resume_text=resume.raw_text or "")
    return ATSResponse(**result.model_dump())


# ── Interview Prep ────────────────────────────────────────────────────────────

@router.post("/interview-prep/{job_id}", response_model=InterviewPrepResponse)
async def generate_interview_questions(
    job_id: str,
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model for this request"),
    provider: str | None = Query(None, description="Override LLM provider for this request"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Generate 12 interview questions across 4 categories with answer frameworks."""
    _check_provider_credentials(provider)
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    try:
        from features.interview_prep import generate_interview_prep
        result = generate_interview_prep(job.to_dict(), _profile_with_id(resume),
                                         model_override=model, provider_override=provider)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[InterviewPrep] job={job_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return InterviewPrepResponse(**result.model_dump())


# ── Company Research ──────────────────────────────────────────────────────────

@router.get("/company-research/{job_id}", response_model=CompanyResearchResponse)
async def get_company_research(
    job_id: str,
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model for this request"),
    provider: str | None = Query(None, description="Override LLM provider for this request"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Mine LinkedIn insights[], JD text, salary hint, and remote policy for company analysis."""
    _check_provider_credentials(provider)
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    try:
        from features.company_research import research_company
        result = research_company(job.to_dict(), _profile_with_id(resume),
                                   model_override=model, provider_override=provider)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[CompanyResearch] job={job_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return CompanyResearchResponse(**result.model_dump())


# ── Salary Benchmark ──────────────────────────────────────────────────────────

@router.get("/salary-benchmark/{job_id}", response_model=SalaryBenchmarkResponse)
async def get_salary_benchmark(
    job_id: str,
    resume_id: str | None = Query(None),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """Extract salary from JD + local-currency market bands + negotiation tips."""
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    from features.salary_benchmark import benchmark_salary
    result = benchmark_salary(job.to_dict(), _profile_with_id(resume))

    data = result.model_dump()
    if data.get("extracted_salary"):
        data["extracted_salary"] = result.extracted_salary.model_dump() if result.extracted_salary else None

    return SalaryBenchmarkResponse(**data)


# ── Tracker Stats ─────────────────────────────────────────────────────────────

@router.get("/tracker-stats", response_model=TrackerStatsResponse)
async def get_tracker_stats(repo: AsyncJobRepository = Depends(get_repo)):
    """Application funnel statistics across all tracked jobs."""
    result = await repo._s.execute(select(Job.status, Job.id))
    rows = result.all()

    from features.tracker import get_application_stats
    stats = get_application_stats([{"status": r.status} for r in rows])
    return TrackerStatsResponse(**stats.model_dump())


# ── Career Path ───────────────────────────────────────────────────────────────

@router.post("/career-path", response_model=CareerPathResponse)
async def generate_career_path(
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model for this request"),
    provider: str | None = Query(None, description="Override LLM provider for this request"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Generate a 3-horizon career plan (now / 6 months / 2 years) and
    prioritised learning roadmap using resume + all matched jobs.
    """
    resume = await _get_resume_or_404(repo, resume_id)

    result = await repo._s.execute(
        select(Job).where(Job.match_score.isnot(None))
    )
    scored_jobs = [j.to_dict() for j in result.scalars().all()]

    if not scored_jobs:
        raise HTTPException(
            status_code=422,
            detail="No matched jobs found. Run the matching pipeline first.",
        )

    _check_provider_credentials(provider)
    try:
        from features.career_path import generate_career_path as _gen
        cp = _gen(_profile_with_id(resume), scored_jobs,
                  model_override=model, provider_override=provider)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("[CareerPath]")
        raise HTTPException(status_code=500, detail=str(e))

    return CareerPathResponse(**cp.model_dump())


# ── Resume Improver ───────────────────────────────────────────────────────────

@router.post("/resume-improve/{job_id}", response_model=ResumeImprovementResponse)
async def improve_resume(
    job_id: str,
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model for this request"),
    provider: str | None = Query(None, description="Override LLM provider for this request"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Generate section-by-section resume improvement suggestions tailored to a specific job.
    Returns grade, per-section rewrites, missing keywords, and a ready-to-paste summary.
    """
    _check_provider_credentials(provider)
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    try:
        from features.resume_improver import improve_resume as _improve
        result = _improve(
            job.to_dict(),
            _profile_with_id(resume),
            resume_text=resume.raw_text or "",
            model_override=model,
            provider_override=provider,
        )
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[ResumeImprover] job={job_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return ResumeImprovementResponse(**result.model_dump())


# ── Company + Salary Intel (combined) ─────────────────────────────────────────

@router.get("/company-intel/{job_id}", response_model=CompanyIntelResponse)
async def get_company_intel(
    job_id: str,
    resume_id: str | None = Query(None),
    model: str | None = Query(None, description="Override LLM model"),
    provider: str | None = Query(None, description="Override LLM provider"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Combined company research + salary intelligence.
    Searches the web for real salary data, then one LLM call for both analyses.
    Requires: pip install duckduckgo-search  (falls back silently if not installed)
    """
    _check_provider_credentials(provider)
    job = await _get_job_or_404(job_id, repo)
    resume = await _get_resume_or_404(repo, resume_id)

    try:
        from features.company_intel import research_company_with_salary
        result = research_company_with_salary(
            job.to_dict(), _profile_with_id(resume),
            model_override=model, provider_override=provider,
        )
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[CompanyIntel] job={job_id}")
        raise HTTPException(status_code=500, detail=str(e))

    return CompanyIntelResponse(**result.model_dump())
