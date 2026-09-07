"""
FastAPI application — entry point.

Run with:
    uvicorn app.main:app --reload --port 8000

Phase 0: only /health and a debug ping-task trigger exist, to prove the
container topology (architecture.md §2) before any real domain logic lands.
Phase 1+ add app/api/routes/{jobs,scrape,resumes,pipelines,features,settings}.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.db import AsyncSessionLocal, check_db_connection
from app.domain.models import SystemPing

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Starting LinkedIn Job Matcher API (v2)…")
    app.state.redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info("Redis pool ready")
    yield
    await app.state.redis.close()
    logger.info("Shutting down.")


app = FastAPI(
    title="LinkedIn Job Matcher API (v2)",
    version="0.0.1",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "LinkedIn Job Matcher API (v2)", "docs": "/docs"}


@app.get("/health")
async def health():
    """Verifies API, DB, and Redis are all reachable — architecture.md §2 exit
    criteria for Phase 0."""
    db_status = await check_db_connection()

    redis_status = "ok"
    try:
        await app.state.redis.ping()
    except Exception as e:
        logger.error(f"[/health] Redis check failed: {e}")
        redis_status = f"error: {e}"

    return {"status": "ok", "db": db_status, "redis": redis_status, "version": "0.0.1"}


# ── Phase 0 smoke-test endpoints — remove once Phase 3's real scrape trigger exists ──

@app.post("/debug/ping", include_in_schema=False)
async def trigger_ping(message: str = "pong"):
    """Enqueues ping_task on the worker; GET /debug/ping-log confirms it landed in Postgres."""
    job = await app.state.redis.enqueue_job("ping_task", message)
    return {"enqueued": True, "job_id": job.job_id}


@app.get("/debug/ping-log", include_in_schema=False)
async def ping_log(limit: int = 10):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SystemPing).order_by(SystemPing.created_at.desc()).limit(limit)
        )
        rows = result.scalars().all()
        return [{"id": r.id, "message": r.message, "created_at": r.created_at.isoformat()} for r in rows]
