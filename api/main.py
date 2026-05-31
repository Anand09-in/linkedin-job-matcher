"""
FastAPI application — entry point.

Run with:
    uvicorn api.main:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)

Phase 4.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.models import ErrorResponse, HealthResponse
from api.routes import scrape, jobs, match, features
from db.database import init_db


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    # Startup
    logger.info("Starting LinkedIn Job Matcher API…")
    await init_db()
    logger.info("Database ready ✓")

    # Validate LLM config on startup (warns but doesn't crash — API still useful for jobs/scrape)
    try:
        from config.settings import get_settings
        get_settings().validate_llm_config()
        logger.info("LLM config valid ✓")
    except ValueError as e:
        logger.warning(f"LLM config warning: {e} — /match endpoint may fail")

    yield

    # Shutdown
    logger.info("Shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="LinkedIn Job Matcher API",
    description=(
        "Scrapes LinkedIn jobs, parses descriptions with AI, "
        "matches against your resume, and surfaces insights like skill gaps."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)


# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # tighten in production (e.g. ["http://localhost:8501"])
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request with method, path, status code, and duration."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info(
        f"{request.method} {request.url.path} "
        f"→ {response.status_code} "
        f"({duration_ms:.0f}ms)"
    )
    return response


# ── Global exception handlers ─────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    logger.warning(f"ValueError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=ErrorResponse(
            detail=str(exc),
            error_type="ValueError",
        ).model_dump(),
    )


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    logger.warning(f"FileNotFoundError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            detail=str(exc),
            error_type="FileNotFoundError",
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            detail="An internal error occurred. Check server logs for details.",
            error_type=type(exc).__name__,
        ).model_dump(),
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(scrape.router)
app.include_router(jobs.router)
app.include_router(match.router)
app.include_router(features.router)


# ── Health & root ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "LinkedIn Job Matcher API", "docs": "/docs"}


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health(request: Request):
    """Health check — verifies API and DB are alive."""
    db_status = "ok"
    try:
        from db.database import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception as e:
        logger.error(f"[/health] DB check failed: {e}")
        db_status = f"error: {e}"

    return HealthResponse(status="ok", db=db_status)
