"""
arq worker entrypoint.

Run with:
    arq app.workers.worker_app.WorkerSettings

architecture.md §1: arq chosen over Celery — asyncio-native (matches FastAPI),
far less operational surface for a single-user local deployment.
"""
from __future__ import annotations

import os

from arq.connections import RedisSettings
from loguru import logger

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.scrapers.bootstrap import bootstrap as bootstrap_scrapers
from app.workers.tasks import ping_task, run_scrape_task, salary_lookup_task

settings = get_settings()

# Unset (default) -> arq's own default queue ("arq:queue"), what the Docker
# worker uses. scripts/start_native_worker.ps1 sets this to
# settings.linkedin_scrape_queue_name so that process — and only that
# process — ever receives run_scrape_task jobs (routes/scrape.py enqueues
# them there specifically). Same WorkerSettings/functions list either way;
# only which queue is polled differs. See config.py's
# linkedin_scrape_queue_name docstring for the account-safety incident this
# is responding to.
_queue_name = os.environ.get("ARQ_QUEUE_NAME")


async def on_startup(ctx):
    configure_logging()
    bootstrap_scrapers()
    logger.info("[worker] started")


async def on_shutdown(ctx):
    logger.info("[worker] shutting down")


class WorkerSettings:
    functions = [ping_task, run_scrape_task, salary_lookup_task]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # A full scrape run (real browser navigation + click-through per job +
    # an LLM call per batch) can run well past arq's 300s default job
    # timeout for anything but a tiny `limit` — 30 minutes covers a
    # realistic full-size run without masking a genuinely hung job forever.
    job_timeout = 1800
    # salary_lookup_task jobs (web search + one LLM call) run concurrently
    # with each other and with any in-progress scrape run — arq's default
    # max_jobs already allows this; nothing extra needed here for FR-5.1's
    # "fire and forget, non-blocking."
    # A future cron entry for pipelines with schedule_cron set goes here too
    # (system-design.md, architecture.md §3.2).


if _queue_name:
    WorkerSettings.queue_name = _queue_name
