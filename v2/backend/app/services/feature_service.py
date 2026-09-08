"""
On-demand features (FR-6, Phase 6) — cover letter, interview prep, company
research, resume improvement, plus two added alongside this phase per user
request: referral outreach message (pairs with Phase 4's referral_service.py,
which only surfaces contacts, never drafts outreach) and negotiation prep
(pairs with Phase 4's automatic salary_service.py enrichment, reusing the
Job.salary_benchmark it already computed rather than searching again).

ATS scoring and career-path planning from v1's `features/` were deliberately
NOT ported — dropped by explicit user decision when this phase was scoped,
not an oversight.

This module is the ONE place that:
  1. Resolves a job_id into the (JobContext, ResumeContext | None) pair every
     llm_tasks/*.py feature module actually consumes — FR-1A.8: the resume
     is always the one the job's pipeline was bound to, never a separate
     "which resume" choice.
  2. Checks the FeatureResult cache before calling the LLM, and writes to it
     after (FR-6.3) — every route in main.py goes through run_feature(),
     never calls an llm_tasks/*.py module directly, so caching can't be
     accidentally bypassed by a new call site later.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from app.core.config import get_settings
from app.domain.exceptions import FeatureRequiresResumeError, UnknownFeatureError
from app.domain.models import Job, Resume
from app.domain.repository import Repository
from app.llm_tasks.company_research import research_company
from app.llm_tasks.cover_letter import generate_cover_letter
from app.llm_tasks.interview_prep import generate_interview_prep
from app.llm_tasks.negotiation_prep import prepare_negotiation
from app.llm_tasks.referral_message import draft_referral_message
from app.llm_tasks.resume_improvement import improve_resume
from app.llm_tasks.schemas import JobContext, ResumeContext, ResumeProfile


def _job_context(job: Job) -> JobContext:
    return JobContext(
        title=job.title,
        company=job.company,
        location=job.location,
        seniority_level=job.seniority_level,
        employment_type=job.employment_type,
        remote_policy=job.remote_policy,
        description=job.description,
        skills_required=job.skills_required or [],
        skills_nice_to_have=job.skills_nice_to_have or [],
        matched_skills=job.matched_skills or [],
        missing_skills=job.missing_skills or [],
        salary_benchmark=job.salary_benchmark,
    )


def _resume_context(resume: Resume) -> ResumeContext:
    profile = ResumeProfile(**resume.parsed_profile) if resume.parsed_profile else ResumeProfile()
    return ResumeContext(
        current_title=profile.current_title,
        total_experience_years=profile.total_experience_years,
        skills=profile.skills,
        summary=profile.summary,
        raw_text=resume.raw_text,
    )


@dataclass
class FeatureSpec:
    needs_resume: bool
    default_params: dict
    run: Callable[[JobContext, Optional[ResumeContext], BaseChatModel, dict], Awaitable[BaseModel]]
    # None means "use core.llm.get_llm()'s own default (DB active setting or
    # env)" — only interview_prep overrides this, see
    # config.llm_interview_prep_max_tokens's docstring for why. main.py reads
    # this BEFORE calling get_llm(), since max_tokens is baked into the
    # Bedrock client at construction time and can't be changed after.
    max_tokens: Optional[int] = None


async def _run_cover_letter(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await generate_cover_letter(job, resume, params["tone"], llm)


async def _run_interview_prep(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await generate_interview_prep(job, resume, llm)


async def _run_company_research(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await research_company(job, llm)


async def _run_resume_improvement(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await improve_resume(job, resume, llm)


async def _run_referral_message(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await draft_referral_message(
        job, resume, llm,
        channel=params["channel"], contact_name=params["contact_name"], contact_title=params["contact_title"],
    )


async def _run_negotiation_prep(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    return await prepare_negotiation(job, resume, llm)


FEATURES: dict[str, FeatureSpec] = {
    "cover_letter": FeatureSpec(
        needs_resume=True, default_params={"tone": "professional"}, run=_run_cover_letter
    ),
    "interview_prep": FeatureSpec(
        needs_resume=True, default_params={}, run=_run_interview_prep,
        max_tokens=get_settings().llm_interview_prep_max_tokens,
    ),
    "company_research": FeatureSpec(needs_resume=False, default_params={}, run=_run_company_research),
    "resume_improvement": FeatureSpec(needs_resume=True, default_params={}, run=_run_resume_improvement),
    "referral_message": FeatureSpec(
        needs_resume=True,
        default_params={"channel": "linkedin_connection_note", "contact_name": None, "contact_title": None},
        run=_run_referral_message,
    ),
    "negotiation_prep": FeatureSpec(needs_resume=True, default_params={}, run=_run_negotiation_prep),
}


def _normalize_params(feature: str, raw_params: dict) -> dict:
    """Only known keys survive, each falling back to its feature's own
    default — so an omitted `tone` and an explicitly-default `tone` produce
    the identical cache key, and an unrelated/typo'd key can't fragment the
    cache silently."""
    spec = FEATURES[feature]
    return {key: raw_params.get(key, default) for key, default in spec.default_params.items()}


def _params_key(params: dict) -> str:
    return json.dumps(params, sort_keys=True)


async def run_feature(
    repo: Repository, feature: str, job_id: uuid.UUID, raw_params: dict, llm: BaseChatModel, regenerate: bool = False
) -> dict[str, Any]:
    if feature not in FEATURES:
        raise UnknownFeatureError(feature, list(FEATURES.keys()))
    spec = FEATURES[feature]

    job = await repo.get_job(job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")

    resume = None
    pipeline = await repo.get_pipeline(job.pipeline_id)
    if pipeline and pipeline.resume_id:
        resume = await repo.get_resume(pipeline.resume_id)

    if spec.needs_resume and resume is None:
        raise FeatureRequiresResumeError(feature, job_id)

    resume_id = resume.id if resume else None
    params = _normalize_params(feature, raw_params)
    params_key = _params_key(params)

    if not regenerate:
        cached = await repo.get_cached_feature_result(job_id, resume_id, feature, params_key)
        if cached is not None:
            return {"feature": feature, "job_id": str(job_id), "params": params, "cached": True, "result": cached.result}

    job_ctx = _job_context(job)
    resume_ctx = _resume_context(resume) if resume else None
    result_model = await spec.run(job_ctx, resume_ctx, llm, params)
    result_dict = result_model.model_dump()

    await repo.save_feature_result(job_id, resume_id, feature, params, params_key, result_dict)
    return {"feature": feature, "job_id": str(job_id), "params": params, "cached": False, "result": result_dict}
