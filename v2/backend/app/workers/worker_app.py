"""
arq worker entrypoint.

Run with:
    arq app.workers.worker_app.WorkerSettings

architecture.md §1: arq chosen over Celery — asyncio-native (matches FastAPI),
far less operational surface for a single-user local deployment.
"""
from __future__ import annotations

from arq.connections import RedisSettings
from loguru import logger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scrapers.bootstrap import bootstrap as bootstrap_scrapers
from app.workers.tasks import ping_task, run_scrape_preview_task

settings = get_settings()


async def on_startup(ctx):
    configure_logging()
    bootstrap_scrapers()
    logger.info("[worker] started")


async def on_shutdown(ctx):
    logger.info("[worker] shutting down")


class WorkerSettings:
    functions = [ping_task, run_scrape_preview_task]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Phase 3/4 add: run_scrape_task, salary_lookup_task, and cron jobs here
    # for pipelines with a schedule_cron set (system-design.md, architecture.md §3.2).
