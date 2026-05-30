"""
FastAPI application entry point.

Run with:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from api.routes import scrape, jobs, match, features
from db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — initialising database…")
    await init_db()
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="LinkedIn Job Matcher API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scrape.router)
app.include_router(jobs.router)
app.include_router(match.router)
app.include_router(features.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
