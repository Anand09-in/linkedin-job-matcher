"""
LLM settings routes (FR-3.1/3.2) — moved here unchanged from Phase 5's
main.py as part of Phase 7's router split (architecture.md §3.4). Phase 8
adds scraper credentials (e.g. LinkedIn's li_at cookie) — previously
LI_AT_COOKIE-env-only, which needed a worker restart to rotate; these are
UI-editable and take effect on the very next scrape run.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.dependencies import get_repo
from app.api.models import (
    LLMSettingResponse,
    LLMSettingUpdateRequest,
    ScraperCredentialCheckResponse,
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


def _credential_response(site: str, credential) -> ScraperCredentialResponse:
    if credential is None:
        return ScraperCredentialResponse(site=site, configured=False)
    return ScraperCredentialResponse(
        site=site, configured=True,
        last_check_status=credential.last_check_status, last_checked_at=credential.last_checked_at,
        updated_at=credential.updated_at,
    )


@router.get("/scraper-credentials/{site}", response_model=ScraperCredentialResponse)
async def get_scraper_credential(site: str, repo: Repository = Depends(get_repo)):
    """Never returns the actual cookie value — `configured` + the last
    check's result/timestamp is all the UI needs to show."""
    return _credential_response(site, await repo.get_scraper_credential(site))


@router.put("/scraper-credentials/{site}", response_model=ScraperCredentialResponse)
async def update_scraper_credential(site: str, body: ScraperCredentialUpdateRequest, repo: Repository = Depends(get_repo)):
    """Takes effect on the very next scrape run for this site — no worker
    restart (the previous LI_AT_COOKIE-env-only setup needed one to rotate
    an expired cookie)."""
    updated = await repo.set_scraper_credential(site, body.value)
    return _credential_response(site, updated)


@router.post("/scraper-credentials/{site}/check", response_model=ScraperCredentialCheckResponse, status_code=202)
async def check_scraper_credential(site: str, request: Request, repo: Repository = Depends(get_repo)):
    """"Test cookie" action — enqueues check_scraper_credential_task on the
    worker (only that image has Playwright to actually ask LinkedIn) and
    returns immediately; poll GET /settings/scraper-credentials/{site} for
    last_check_status, same shape as polling a scrape run."""
    if await repo.get_scraper_credential(site) is None:
        raise HTTPException(status_code=404, detail=f"No credential configured for site={site!r} yet")

    job = await request.app.state.redis.enqueue_job("check_scraper_credential_task", site)
    return ScraperCredentialCheckResponse(enqueued=True, job_id=job.job_id, site=site)
