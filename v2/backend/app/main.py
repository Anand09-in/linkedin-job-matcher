"""
FastAPI application — entry point.

Run with:
    uvicorn app.main:app --reload --port 8000

Phase 7: this file is now just the composition root — lifespan, health, and
`include_router()` for every real router in app/api/routes/. Phases 0-6 grew
their endpoints directly on this module (`/debug/*` prototyping endpoints
plus a few real ones bolted on as each phase needed to be exercised
manually); Phase 7's job is exactly to finish that migration — every
`/debug/*` endpoint listed in git history for this file has a real,
documented, response-modeled replacement in app/api/routes/ now, so none of
them are carried forward here.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from app.api.routes import export, features, jobs, pipelines, resumes, scrape, settings as settings_routes
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.domain.db import check_db_connection

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

# Phase 8: the frontend (localhost:5173) and this API (localhost:8000) are
# different origins by port alone, even on the same machine — without this,
# the browser blocks every request the frontend makes with a CORS error,
# caught live while verifying the frontend in a real browser (not something
# `tsc`/`vite build` or the backend's own test suite could ever catch, since
# CORS is enforced by the browser, not the server under test).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(scrape.router)
app.include_router(resumes.router)
app.include_router(pipelines.router)
app.include_router(settings_routes.router)
app.include_router(features.router)
app.include_router(export.router)


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "LinkedIn Job Matcher API (v2)", "docs": "/docs"}


class HealthResponse(BaseModel):
    status: str
    db: str
    redis: str
    version: str


@app.get("/health", response_model=HealthResponse)
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

    return HealthResponse(status="ok", db=db_status, redis=redis_status, version="0.0.1")
