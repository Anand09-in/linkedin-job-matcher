"""
LLM settings routes (FR-3.1/3.2) — moved here unchanged from Phase 5's
main.py as part of Phase 7's router split (architecture.md §3.4).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repo
from app.api.models import LLMSettingResponse, LLMSettingUpdateRequest
from app.core.config import get_settings
from app.domain.repository import Repository

router = APIRouter(prefix="/settings", tags=["Settings"])
settings = get_settings()


@router.get("/llm", response_model=LLMSettingResponse)
async def get_llm_setting(repo: Repository = Depends(get_repo)):
    """Falls back to the env-configured default if no LLMSetting row has
    been created yet (first boot, before PUT has ever been called)."""
    active = await repo.get_active_llm_setting()
    if active is None:
        return LLMSettingResponse(
            provider="bedrock", model=settings.bedrock_model,
            temperature=settings.llm_temperature, max_tokens=settings.llm_max_tokens,
        )
    return LLMSettingResponse(
        provider=active.provider, model=active.model, temperature=active.temperature, max_tokens=active.max_tokens
    )


@router.put("/llm", response_model=LLMSettingResponse)
async def update_llm_setting(body: LLMSettingUpdateRequest, repo: Repository = Depends(get_repo)):
    """Takes effect on the very next get_llm() call — a new scrape run's
    extraction and any on-demand feature call both pick it up with no
    container restart (Phase 5 exit criterion, plan.md)."""
    updated = await repo.set_active_llm_setting(
        provider=body.provider, model=body.model, temperature=body.temperature, max_tokens=body.max_tokens
    )
    return LLMSettingResponse(
        provider=updated.provider, model=updated.model, temperature=updated.temperature, max_tokens=updated.max_tokens
    )
