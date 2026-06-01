"""
APScheduler — Phase 7.3

Background scraper scheduler. Enable via .env:
    SCHEDULER_ENABLED=true
    SCHEDULER_INTERVAL_HOURS=12   # default 12

Uses AsyncIOScheduler so it shares the FastAPI event loop without blocking.
"""
from __future__ import annotations

from loguru import logger

_scheduler = None


async def start_scheduler() -> None:
    """Start the background scheduler if SCHEDULER_ENABLED=true."""
    from config.settings import get_settings
    settings = get_settings()

    if not settings.scheduler_enabled:
        logger.info("[Scheduler] Disabled (SCHEDULER_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning(
            "[Scheduler] apscheduler not installed — scheduler disabled. "
            "Run: pip install apscheduler"
        )
        return

    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_scrape,
        trigger="interval",
        hours=settings.scheduler_interval_hours,
        id="auto_scrape",
        replace_existing=True,
        max_instances=1,       # never run two scrapes concurrently
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info(
        f"[Scheduler] Started — scraping every {settings.scheduler_interval_hours}h "
        f"(next run: {_scheduler.get_job('auto_scrape').next_run_time})"
    )


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler on shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")


async def _run_scrape() -> None:
    """The job function: runs a full scrape in a thread so it doesn't block the loop."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    logger.info("[Scheduler] Scheduled scrape starting…")
    try:
        from scraper.service import ScraperService
        service = ScraperService()
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(
                pool,
                lambda: service.run_sync(config_snapshot={"trigger": "scheduler"}),
            )
        stats = result.get("stats", {})
        logger.info(
            f"[Scheduler] Scrape complete — "
            f"new={stats.get('new',0)} updated={stats.get('updated',0)} "
            f"errors={stats.get('errors',0)} rate_limited={stats.get('rate_limited',0)}"
        )
    except Exception as e:
        logger.exception(f"[Scheduler] Scrape failed: {e}")
