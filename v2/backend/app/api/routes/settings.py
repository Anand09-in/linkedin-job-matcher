"""
LLM settings routes (FR-3.1/3.2) — moved here unchanged from Phase 5's
main.py as part of Phase 7's router split (architecture.md §3.4). Phase 8
adds scraper credentials (e.g. LinkedIn's li_at cookie) — previously
LI_AT_COOKIE-env-only, which needed a worker restart to rotate; these are
UI-editable and take effect on the very next scrape run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_repo
from app.api.models import (
    LLMSettingResponse,
    LLMSettingUpdateRequest,
    ScraperCredentialResponse,
    ScraperCredentialUpdateRequest,
)
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


def _mask(value: str) -> str:
    """Last 4 characters only — enough for a user to recognize "yes, that's
    the cookie I just pasted" without the response ever carrying anything a
    logged request/browser history entry could replay."""
    tail = value[-4:] if len(value) > 4 else value
    return f"{'•' * 10}{tail}"


def _credential_response(site: str, credential) -> ScraperCredentialResponse:
    if credential is None:
        return ScraperCredentialResponse(site=site, configured=False)
    return ScraperCredentialResponse(
        site=site, configured=True, masked_value=_mask(credential.value),
        last_check_status=credential.last_check_status, last_checked_at=credential.last_checked_at,
        updated_at=credential.updated_at,
    )


@router.get("/scraper-credentials/{site}", response_model=ScraperCredentialResponse)
async def get_scraper_credential(site: str, repo: Repository = Depends(get_repo)):
    """Never returns the full cookie value — `masked_value` (last 4 chars)
    plus the last check's result/timestamp is enough for the UI to show
    what's stored without exposing the working credential."""
    return _credential_response(site, await repo.get_scraper_credential(site))


@router.put("/scraper-credentials/{site}", response_model=ScraperCredentialResponse)
async def update_scraper_credential(
    site: str, body: ScraperCredentialUpdateRequest, request: Request, repo: Repository = Depends(get_repo)
):
    """
    Takes effect on the very next scrape run for this site — no worker
    restart (the previous LI_AT_COOKIE-env-only setup needed one to rotate
    an expired cookie).

    Also auto-enqueues a validity check (check_scraper_credential_task) right
    away — per explicit user feedback, saving a cookie and finding out
    whether it actually works shouldn't be two separate steps. The response
    still comes back with last_check_status=null (the check runs on the
    worker, in the background); the frontend's poll on GET picks up the
    result a few seconds later, same as it already did for the standalone
    "Test cookie" action this replaces.
    """
    updated = await repo.set_scraper_credential(site, body.value)
    await request.app.state.redis.enqueue_job("check_scraper_credential_task", site)
    return _credential_response(site, updated)
