"""
On-demand features (FR-6, Phase 6) — cover letter, interview prep, company
research, resume improvement, plus referral outreach message (pairs with
Phase 4's referral_service.py, which only surfaces contacts, never drafts
outreach), added alongside this phase per user request.
A 6th, `referral_search`, was added in Phase 7 when retiring `/debug/*`
endpoints surfaced that Phase 4's actual referral-contact search had no
real, non-debug replacement — see `_run_referral_search`'s docstring.

ATS scoring and career-path planning from v1's `features/` were deliberately
NOT ported — dropped by explicit user decision when this phase was scoped,
not an oversight. `negotiation_prep` (originally paired with Phase 4's
salary_service.py enrichment) was removed post-Phase-8 per explicit user
feedback: its content didn't vary per job in any way the user found useful,
so it was cut rather than kept as dead weight.

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
from app.llm_tasks.all_features import generate_all_features
from app.llm_tasks.company_research import research_company
from app.llm_tasks.cover_letter import generate_cover_letter
from app.llm_tasks.interview_prep import generate_interview_prep
from app.llm_tasks.referral_message import draft_referral_message
from app.llm_tasks.resume_improvement import improve_resume
from app.llm_tasks.schemas import JobContext, ResumeContext, ResumeProfile
from app.services.referral_service import find_referral_contacts

# The four "generate straight from job+resume" features bundled into one LLM
# call by run_all_features() below — see AllFeaturesResult's docstring for
# why referral_message/referral_search are excluded.
_BUNDLED_FEATURES = ("cover_letter", "interview_prep", "company_research", "resume_improvement")


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


def _fix_mojibake(text: str) -> str:
    """
    Repairs UTF-8 text that a model emitted mis-encoded as cp1252 — confirmed
    live in a referral_message output ("Zscalerâ€™s" instead
    of "Zscaler's"): the model apparently reproduced training-data mojibake
    verbatim for curly apostrophes/quotes/dashes rather than actually
    mis-decoding bytes on our side (the API layer is UTF-8 end to end).
    Round-tripping through cp1252-encode -> utf-8-decode only succeeds when
    the text really is this specific corruption, so this can't misfire on
    ordinary text.
    """
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _fix_mojibake_recursive(value: Any) -> Any:
    if isinstance(value, str):
        return _fix_mojibake(value)
    if isinstance(value, list):
        return [_fix_mojibake_recursive(v) for v in value]
    if isinstance(value, dict):
        return {k: _fix_mojibake_recursive(v) for k, v in value.items()}
    return value


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
    return await generate_cover_letter(job, resume, params["tone"], params["word_count"], llm)


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


async def _run_referral_search(job: JobContext, resume: Optional[ResumeContext], llm: BaseChatModel, params: dict) -> BaseModel:
    """The actual web search for candidate referral contacts (Phase 4's
    referral_service.py — web-search-only, never LinkedIn scraping, see that
    module's docstring). Distinct from `referral_message`, which drafts
    outreach text to a contact you already have — this is how you find one
    in the first place. Originally only reachable via Phase 4's
    `/debug/referral-contacts`; promoted to a real feature here since Phase
    7 retires every `/debug/*` endpoint and this one had no other real
    replacement in architecture.md's planned surface — an oversight in how
    Phase 6 was scoped, not a deliberate exclusion like ATS score/career
    path were."""
    return await find_referral_contacts(job.company, job.title, llm)


FEATURES: dict[str, FeatureSpec] = {
    "cover_letter": FeatureSpec(
        needs_resume=True, default_params={"tone": "professional", "word_count": 250}, run=_run_cover_letter
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
    "referral_search": FeatureSpec(needs_resume=False, default_params={}, run=_run_referral_search),
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


async def _resolve_job_and_resume(repo: Repository, job_id: uuid.UUID) -> tuple[Job, Optional[Resume]]:
    """FR-1A.8: the resume is always the one the job's pipeline was bound
    to, never a separate "which resume" choice — shared by run_feature()
    and run_all_features() so there's exactly one place this lookup lives."""
    job = await repo.get_job(job_id)
    if job is None:
        raise LookupError(f"Job {job_id} not found")

    resume = None
    pipeline = await repo.get_pipeline(job.pipeline_id)
    if pipeline and pipeline.resume_id:
        resume = await repo.get_resume(pipeline.resume_id)
    return job, resume


async def run_feature(
    repo: Repository, feature: str, job_id: uuid.UUID, raw_params: dict, llm: BaseChatModel, regenerate: bool = False
) -> dict[str, Any]:
    if feature not in FEATURES:
        raise UnknownFeatureError(feature, list(FEATURES.keys()))
    spec = FEATURES[feature]

    job, resume = await _resolve_job_and_resume(repo, job_id)
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
    result_dict = _fix_mojibake_recursive(result_model.model_dump())

    await repo.save_feature_result(job_id, resume_id, feature, params, params_key, result_dict)
    return {"feature": feature, "job_id": str(job_id), "params": params, "cached": False, "result": result_dict}


async def run_all_features(
    repo: Repository, job_id: uuid.UUID, tone: str, word_count: int, llm: BaseChatModel, regenerate: bool = False
) -> dict[str, Any]:
    """
    One combined LLM call for _BUNDLED_FEATURES (2026-09-08, explicit user
    request) — opening a job's on-demand features costs one LLM call, not
    four independent ones. referral_message/referral_search stay reachable
    only through run_feature(), unchanged (see AllFeaturesResult's
    docstring for why bundling those wouldn't make sense).

    Writes each of the four results into the exact same per-feature
    FeatureResult cache run_feature() itself reads/writes — same params,
    same params_key a standalone call for that one feature would use — so
    a later single-feature "Regenerate" on the Job Detail page keeps
    working exactly as before and never needs to know this bundled path
    exists. Symmetrically, if all four are already cached (e.g. a prior
    bundle call, or someone regenerated each individually) and
    regenerate=False, this returns the cached bundle with zero LLM calls.
    """
    job, resume = await _resolve_job_and_resume(repo, job_id)
    if resume is None:
        # All four bundled features need a resume (company_research is the
        # only individually-resume-optional one of the four, but the
        # bundle as a whole can't skip it).
        raise FeatureRequiresResumeError("all_features", job_id)

    resume_id = resume.id
    per_feature_params = {
        "cover_letter": _normalize_params("cover_letter", {"tone": tone, "word_count": word_count}),
        "interview_prep": {},
        "company_research": {},
        "resume_improvement": {},
    }
    per_feature_keys = {f: _params_key(p) for f, p in per_feature_params.items()}

    if not regenerate:
        cached_results: Optional[dict[str, dict]] = {}
        for f in _BUNDLED_FEATURES:
            cached = await repo.get_cached_feature_result(job_id, resume_id, f, per_feature_keys[f])
            if cached is None:
                cached_results = None
                break
            cached_results[f] = cached.result
        if cached_results is not None:
            return {"job_id": str(job_id), "cached": True, "results": cached_results}

    job_ctx = _job_context(job)
    resume_ctx = _resume_context(resume)
    combined = await generate_all_features(job_ctx, resume_ctx, tone, word_count, llm)

    results: dict[str, dict] = {}
    for f in _BUNDLED_FEATURES:
        result_dict = _fix_mojibake_recursive(getattr(combined, f).model_dump())
        await repo.save_feature_result(job_id, resume_id, f, per_feature_params[f], per_feature_keys[f], result_dict)
        results[f] = result_dict

    return {"job_id": str(job_id), "cached": False, "results": results}
