"""
FastAPI application — entry point.

Run with:
    uvicorn app.main:app --reload --port 8000

Phase 0: only /health and a debug ping-task trigger exist, to prove the
container topology (architecture.md §2) before any real domain logic lands.
Phase 1+ add app/api/routes/{jobs,scrape,resumes,pipelines,features,settings}.py.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.db import AsyncSessionLocal, check_db_connection
from app.domain.models import SystemPing
from app.domain.repository import Repository

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Starting LinkedIn Job Matcher API (v2)…")
    app.state.redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("Redis pool ready")
    yield
    await app.state.redis.close()
    logger.info("Shutting down.")


app = FastAPI(
    title="LinkedIn Job Matcher API (v2)",
    version="0.0.1",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "LinkedIn Job Matcher API (v2)", "docs": "/docs"}


@app.get("/health")
async def health():
    """Verifies API, DB, and Redis are all reachable — architecture.md §2 exit
    criteria for Phase 0."""
    db_status = await check_db_connection()

    redis_status = "ok"
    try:
        await app.state.redis.ping()
    except Exception as e:
        logger.error(f"[/health] Redis check failed: {e}")
        redis_status = f"error: {e}"

    return {"status": "ok", "db": db_status, "redis": redis_status, "version": "0.0.1"}


# ── Phase 5 (FR-3.1/3.2): the one active LLM config, read by core/llm.py on
#    every call site. Real, non-debug endpoint — plan.md names it explicitly
#    as the exception to "everything else waits for Phase 7". ──────────────

class LLMSettingResponse(BaseModel):
    provider: str
    model: str
    temperature: float
    max_tokens: int


class LLMSettingUpdateRequest(BaseModel):
    provider: str = "bedrock"
    model: str
    temperature: float = 0.1
    max_tokens: int = 2000


@app.get("/settings/llm", response_model=LLMSettingResponse)
async def get_llm_setting():
    """Falls back to the env-configured default if no LLMSetting row has
    been created yet (first boot, before PUT has ever been called)."""
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        active = await repo.get_active_llm_setting()
        if active is None:
            return LLMSettingResponse(
                provider="bedrock",
                model=settings.bedrock_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )
        return LLMSettingResponse(
            provider=active.provider, model=active.model,
            temperature=active.temperature, max_tokens=active.max_tokens,
        )


@app.put("/settings/llm", response_model=LLMSettingResponse)
async def update_llm_setting(body: LLMSettingUpdateRequest):
    """Takes effect on the very next get_llm() call — a new scrape run's
    extraction and any on-demand feature call both pick it up with no
    container restart (Phase 5 exit criterion, plan.md)."""
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        updated = await repo.set_active_llm_setting(
            provider=body.provider, model=body.model,
            temperature=body.temperature, max_tokens=body.max_tokens,
        )
        return LLMSettingResponse(
            provider=updated.provider, model=updated.model,
            temperature=updated.temperature, max_tokens=updated.max_tokens,
        )


# ── Phase 0 smoke-test endpoints — remove once Phase 3's real scrape trigger exists ──

@app.post("/debug/ping", include_in_schema=False)
async def trigger_ping(message: str = "pong"):
    """Enqueues ping_task on the worker; GET /debug/ping-log confirms it landed in Postgres."""
    job = await app.state.redis.enqueue_job("ping_task", message)
    return {"enqueued": True, "job_id": job.job_id}


@app.get("/debug/ping-log", include_in_schema=False)
async def ping_log(limit: int = 10):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SystemPing).order_by(SystemPing.created_at.desc()).limit(limit)
        )
        rows = result.scalars().all()
        return [{"id": r.id, "message": r.message, "created_at": r.created_at.isoformat()} for r in rows]


# ── Debug/manual-test endpoints — remain until Phase 7 builds the real
#    /pipelines, /resumes, /scrape, /jobs REST surface with proper request/
#    response models, auth-ready shape, etc. These exist ONLY so each phase
#    could be exercised manually against real Postgres/Redis/LinkedIn/Bedrock
#    without waiting for Phase 7. ──────────────────────────────────────────────

class QuickResumeRequest(BaseModel):
    name: str
    raw_text: str


@app.post("/debug/quick-resume", include_in_schema=False)
async def create_quick_resume(body: QuickResumeRequest):
    """Create a minimal Resume for manual testing — Phase 7 replaces this
    with a real POST /resumes (PDF upload + parsing, api/routes/resumes.py)."""
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        resume = await repo.create_resume(name=body.name, filename=f"{body.name}.txt", raw_text=body.raw_text)
        return {"resume_id": str(resume.id), "name": resume.name}


@app.post("/debug/quick-pipeline", include_in_schema=False)
async def create_quick_pipeline(
    name: str,
    query: str,
    site: str = "linkedin",
    locations: str = "",
    batch_size: int = 5,
    resume_id: Optional[str] = None,
    min_match_score_override: Optional[float] = None,
    max_experience_years_override: Optional[int] = None,
):
    """Create a minimal Pipeline for manual testing — Phase 7 replaces this
    with a real POST /pipelines endpoint.

    `locations` is semicolon-separated, NOT comma-separated: a single location
    like "Bangalore, India" already contains a comma, so splitting on "," was
    silently turning one real location into two bogus ones ("Bangalore" and
    "India" as separate filters) — caught during Phase 2 live testing when a
    pipeline created this way returned zero live results for either half.
    """
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        pipeline = await repo.create_pipeline(
            name=name,
            site=site,
            query=query,
            locations=[loc.strip() for loc in locations.split(";") if loc.strip()],
            batch_size=batch_size,
            resume_id=uuid.UUID(resume_id) if resume_id else None,
            min_match_score_override=min_match_score_override,
            max_experience_years_override=max_experience_years_override,
        )
        return {
            "pipeline_id": str(pipeline.id), "name": pipeline.name, "site": pipeline.site,
            "resume_id": str(pipeline.resume_id) if pipeline.resume_id else None,
        }


@app.post("/debug/scrape", include_in_schema=False)
async def trigger_scrape(pipeline_id: str, limit: Optional[int] = None):
    """Enqueues run_scrape_task — the real Phase 3 pipeline: scrape ->
    extract+match (one LLM call per batch) -> deterministic filter -> save.
    GET /debug/jobs, /debug/rejected-jobs, /debug/scrape-runs inspect the
    result. Requires LI_AT_COOKIE in .env for site=linkedin pipelines."""
    job = await app.state.redis.enqueue_job("run_scrape_task", pipeline_id, limit)
    return {"enqueued": True, "job_id": job.job_id}


@app.get("/debug/jobs", include_in_schema=False)
async def debug_list_jobs(pipeline_id: Optional[str] = None, limit: int = 20):
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        jobs = await repo.list_jobs(
            pipeline_id=uuid.UUID(pipeline_id) if pipeline_id else None, limit=limit
        )
        return [
            {
                "id": str(j.id),
                "title": j.title,
                "company": j.company,
                "location": j.location,
                "match_score": j.match_score,
                "matched_skills": j.matched_skills,
                "missing_skills": j.missing_skills,
                "skills_required": j.skills_required,
                "seniority_level": j.seniority_level,
                "employment_type": j.employment_type,
                "remote_policy": j.remote_policy,
                "experience_years_min": j.experience_years_min,
                "match_rationale": j.match_rationale,
                "date_posted": j.date_posted.isoformat() if j.date_posted else None,
                "link": j.link,
                "salary_benchmark": j.salary_benchmark,
                "salary_enrichment_status": j.salary_enrichment_status,
            }
            for j in jobs
        ]


@app.get("/debug/rejected-jobs", include_in_schema=False)
async def debug_list_rejected_jobs(pipeline_id: Optional[str] = None, limit: int = 20):
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        rejected = await repo.list_rejected_jobs(
            pipeline_id=uuid.UUID(pipeline_id) if pipeline_id else None, limit=limit
        )
        return [
            {"title": r.title, "company": r.company, "match_score": r.match_score, "reason": r.reason, "link": r.link}
            for r in rejected
        ]


@app.get("/debug/scrape-runs", include_in_schema=False)
async def debug_list_scrape_runs(pipeline_id: str, limit: int = 10):
    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        runs = await repo.list_scrape_runs(pipeline_id=uuid.UUID(pipeline_id), limit=limit)
        return [
            {
                "id": str(r.id),
                "status": r.status,
                "jobs_seen": r.jobs_seen,
                "jobs_saved": r.jobs_saved,
                "jobs_rejected": r.jobs_rejected,
                "errors": r.errors,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ]


# ── Phase 4: salary enrichment (automatic) + referral contacts (on-demand) ──

@app.post("/debug/trigger-salary-lookup", include_in_schema=False)
async def trigger_salary_lookup(job_id: str):
    """Manually enqueue salary_lookup_task for one job — in production this
    is enqueued automatically by scrape_service.py right after the job is
    saved (FR-5.1); this exists only to test/re-run it without a full scrape."""
    job = await app.state.redis.enqueue_job("salary_lookup_task", job_id)
    return {"enqueued": True, "job_id": job.job_id}


@app.get("/debug/referral-contacts", include_in_schema=False)
async def debug_referral_contacts(
    company: Optional[str] = None,
    job_title: Optional[str] = None,
    job_id: Optional[str] = None,
):
    """
    On-demand, synchronous (FR-6.2-style) referral-contact search — web
    search only, never LinkedIn scraping (see referral_service.py's module
    docstring for why). Pass either job_id (looks up company/title from a
    real Job row) or company+job_title directly (useful for testing without
    a real scraped job).
    """
    from app.core.llm import get_llm
    from app.services.referral_service import find_referral_contacts

    if job_id:
        async with AsyncSessionLocal() as session:
            repo = Repository(session)
            job = await repo.get_job(uuid.UUID(job_id))
            if job is None:
                return {"error": f"Job {job_id} not found"}
            company, job_title = job.company, job.title

    if not company or not job_title:
        return {"error": "Provide either job_id, or both company and job_title"}

    result = await find_referral_contacts(company, job_title, await get_llm())
    return result.model_dump()


# ── Phase 6: on-demand features (FR-6) — real, non-debug endpoint per plan.md,
#    same exception as Phase 5's /settings/llm to the "everything waits for
#    Phase 7" rule. ────────────────────────────────────────────────────────

class FeatureRequestBody(BaseModel):
    """Optional per-feature parameters — most features need none of these.
    Unrecognized/inapplicable keys are silently ignored by
    feature_service._normalize_params (each feature only reads its own
    declared default_params), so one shared body model can cover every
    feature without per-feature request schemas."""

    tone: Optional[str] = None
    channel: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    regenerate: bool = False


@app.post("/features/{feature}/{job_id}")
async def run_on_demand_feature(feature: str, job_id: str, body: FeatureRequestBody = FeatureRequestBody()):
    """
    FR-6.2: synchronous on-demand feature call (button click -> loading
    state -> result), no queue. FR-6.3: cached per (job, resume, feature,
    params) — a second identical request is served from the cache without a
    new LLM call, unless `regenerate: true` is passed.

    Known features (see feature_service.FEATURES for the authoritative
    list/params): cover_letter (tone), interview_prep, company_research (no
    resume needed), resume_improvement, referral_message (channel,
    contact_name, contact_title), negotiation_prep.
    """
    from app.core.llm import get_llm
    from app.domain.exceptions import FeatureRequiresResumeError, UnknownFeatureError
    from app.services.feature_service import FEATURES, run_feature

    raw_params = {k: v for k, v in body.model_dump().items() if k != "regenerate" and v is not None}
    # max_tokens is baked into the Bedrock client at construction time, so a
    # feature needing more headroom (interview_prep) must request it via
    # get_llm() itself, not after — see FeatureSpec.max_tokens's docstring.
    spec = FEATURES.get(feature)

    async with AsyncSessionLocal() as session:
        repo = Repository(session)
        try:
            llm = await get_llm(max_tokens=spec.max_tokens if spec else None)
            return await run_feature(repo, feature, uuid.UUID(job_id), raw_params, llm, regenerate=body.regenerate)
        except UnknownFeatureError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except FeatureRequiresResumeError as e:
            raise HTTPException(status_code=422, detail=str(e))
