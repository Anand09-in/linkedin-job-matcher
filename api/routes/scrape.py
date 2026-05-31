"""
Scraper routes.

POST /scrape           — trigger a background LinkedIn scrape
GET  /scrape/{run_id}  — poll status of a running/completed scrape
GET  /scrape/           — list all past scrape runs

Phase 4.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_repo
from api.models import ScrapeRequest, ScrapeStatusResponse
from db.database import get_db
from db.models import ScrapeRun
from db.repository import AsyncJobRepository

router = APIRouter(prefix="/scrape", tags=["Scraper"])


# ── Background worker ─────────────────────────────────────────────────────────

def _run_scraper_in_thread(query_overrides: Optional[list[dict]], run_id: str) -> None:
    """
    Runs ScraperService.run_sync() in a background thread.
    Passes the pre-created run_id so the scraper updates the same record.
    """
    try:
        from scraper.service import ScraperService
        service = ScraperService()

        if query_overrides:
            service._query_cfgs = query_overrides
            logger.info(f"[/scrape] Using {len(query_overrides)} overridden queries")

        result = service.run_sync(run_id=run_id)
        logger.info(
            f"[/scrape] Background scrape complete — "
            f"run_id={result['run_id']} jobs={len(result['jobs'])}"
        )
    except Exception as e:
        logger.exception(f"[/scrape] Background scrape failed: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=ScrapeStatusResponse, status_code=202)
async def trigger_scrape(
    body: ScrapeRequest,
    background_tasks: BackgroundTasks,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Start a LinkedIn scrape in the background.

    Returns 202 Accepted immediately with a run_id.
    Poll GET /scrape/{run_id} to check progress.

    - Scraping runs in a background thread (Selenium is blocking).
    - Jobs are upserted to SQLite as they arrive (no data lost on crash).
    - Use query_overrides to run a one-off search without editing config.yaml.
    """
    from config.settings import get_settings
    settings = get_settings()

    if not settings.li_at_cookie:
        raise HTTPException(
            status_code=400,
            detail="LI_AT_COOKIE is not set in .env. See README for instructions."
        )

    # Create ScrapeRun record immediately so the client has a run_id to poll
    from db.repository import SyncJobRepository, SyncSession
    with SyncSession() as session:
        sync_repo = SyncJobRepository(session)
        run_id = sync_repo.create_scrape_run(
            config_snapshot={"queries": body.queries or "from_config"}
        )

    # Kick off background thread
    # Using threading directly because Selenium is not async-compatible
    thread = threading.Thread(
        target=_run_scraper_in_thread,
        args=(body.queries, run_id),
        daemon=True,
        name=f"scraper-{run_id}",
    )
    thread.start()

    logger.info(f"[POST /scrape] Started run_id={run_id}")

    return ScrapeStatusResponse(
        run_id=run_id,
        status="running",
        jobs_found=0,
        started_at=__import__("datetime").datetime.utcnow(),
    )


@router.get("/runs", response_model=list[ScrapeStatusResponse])
async def list_scrape_runs(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """List the most recent scrape runs."""
    result = await db.execute(
        select(ScrapeRun)
        .order_by(ScrapeRun.started_at.desc())
        .limit(limit)
    )
    runs = result.scalars().all()
    return [
        ScrapeStatusResponse(
            run_id=r.id,
            status=r.status,
            jobs_found=r.jobs_found,
            started_at=r.started_at,
            finished_at=r.finished_at,
            error=r.error,
        )
        for r in runs
    ]


@router.get("/{run_id}", response_model=ScrapeStatusResponse)
async def get_scrape_status(
    run_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Poll the status of a scrape run.

    Status values: running | completed | failed
    """
    run = await repo.get_scrape_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Scrape run '{run_id}' not found")

    return ScrapeStatusResponse(
        run_id=run.id,
        status=run.status,
        jobs_found=run.jobs_found,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )
