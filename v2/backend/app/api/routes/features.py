"""
On-demand feature routes (FR-6) — moved here unchanged in behavior from
Phase 6's main.py as part of Phase 7's router split (architecture.md §3.4).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_repo
from app.api.models import AllFeaturesRequestBody, AllFeaturesRunResponse, FeatureRequestBody, FeatureRunResponse
from app.core.config import get_settings
from app.core.llm import get_llm
from app.domain.exceptions import FeatureRequiresResumeError, UnknownFeatureError
from app.domain.repository import Repository
from app.services.feature_service import FEATURES, run_all_features, run_feature

router = APIRouter(prefix="/features", tags=["Features"])
settings = get_settings()


@router.post("/all/{job_id}", response_model=AllFeaturesRunResponse)
async def run_all_on_demand_features(
    job_id: uuid.UUID, body: AllFeaturesRequestBody = AllFeaturesRequestBody(), repo: Repository = Depends(get_repo)
):
    """
    Cover letter + interview prep + company research + resume improvement
    in ONE LLM call (2026-09-08, explicit user request — see
    feature_service.run_all_features's docstring). referral_message/
    referral_search stay reachable only through POST /{feature}/{job_id}
    above, unchanged.
    """
    try:
        llm = await get_llm(max_tokens=settings.llm_all_features_max_tokens)
        return await run_all_features(
            repo, job_id, tone=body.tone, word_count=body.word_count, llm=llm, regenerate=body.regenerate
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FeatureRequiresResumeError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{feature}/{job_id}", response_model=FeatureRunResponse)
async def run_on_demand_feature(
    feature: str, job_id: uuid.UUID, body: FeatureRequestBody = FeatureRequestBody(), repo: Repository = Depends(get_repo)
):
    """
    FR-6.2: synchronous on-demand feature call (button click -> loading
    state -> result), no queue. FR-6.3: cached per (job, resume, feature,
    params) — a second identical request is served from the cache without a
    new LLM call, unless `regenerate: true` is passed.

    Known features (see feature_service.FEATURES for the authoritative
    list/params): cover_letter (tone, word_count), interview_prep,
    company_research (no resume needed), resume_improvement,
    referral_message (channel, contact_name, contact_title), referral_search
    (no resume needed).
    """
    raw_params = {k: v for k, v in body.model_dump().items() if k != "regenerate" and v is not None}
    # max_tokens is baked into the Bedrock client at construction time, so a
    # feature needing more headroom (interview_prep) must request it via
    # get_llm() itself, not after — see FeatureSpec.max_tokens's docstring.
    spec = FEATURES.get(feature)

    try:
        llm = await get_llm(max_tokens=spec.max_tokens if spec else None)
        return await run_feature(repo, feature, job_id, raw_params, llm, regenerate=body.regenerate)
    except UnknownFeatureError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FeatureRequiresResumeError as e:
        raise HTTPException(status_code=422, detail=str(e))
