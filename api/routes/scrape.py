"""
POST /scrape  — trigger a background scrape run
GET  /scrape/{run_id} — check run status

Phase 4 implementation.
TODO: wire ScraperService and DB persistence.
"""
from __future__ import annotations
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import ScrapeRequest, ScrapeStatusResponse
from db.database import get_db

router = APIRouter(prefix="/scrape", tags=["scraper"])


@router.post("/", response_model=ScrapeStatusResponse)
async def trigger_scrape(
    request: ScrapeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a LinkedIn scrape in the background.
    Returns a run_id to poll for status.
    TODO Phase 4: create ScrapeRun record, enqueue ScraperService.run_sync().
    """
    raise NotImplementedError("Phase 4")


@router.get("/{run_id}", response_model=ScrapeStatusResponse)
async def get_scrape_status(run_id: str, db: AsyncSession = Depends(get_db)):
    """Return status of a scrape run by ID. TODO Phase 4."""
    raise NotImplementedError("Phase 4")
