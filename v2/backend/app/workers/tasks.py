"""
arq task functions. Phase 0: a single trivial task (ping_task) proves
worker -> Redis -> Postgres wiring end to end (plan.md Phase 0 exit criteria).

Phase 3/4 add run_scrape_task and salary_lookup_task here.
"""
from __future__ import annotations

from loguru import logger

from app.domain.db import AsyncSessionLocal
from app.domain.models import SystemPing


async def ping_task(ctx, message: str = "pong") -> dict:
    """Writes a SystemPing row to Postgres and returns its id — the arq result
    (visible via `await redis.get(job.job_id ...)` / arq's result store) plus
    the DB row are the two independent ways to confirm this ran."""
    async with AsyncSessionLocal() as session:
        ping = SystemPing(message=message)
        session.add(ping)
        await session.commit()
        await session.refresh(ping)
        logger.info(f"[ping_task] wrote SystemPing id={ping.id} message={message!r}")
        return {"id": ping.id, "message": ping.message}
