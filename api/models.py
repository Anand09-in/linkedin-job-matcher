"""
Pydantic v2 request/response models for the FastAPI layer.
Single source of truth for all API shapes.

Phase 4.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Scraper ───────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    """Body for POST /scrape — all fields optional, defaults come from config.yaml."""
    queries: Optional[list[dict]] = Field(
        None,
        description="Override queries list from config.yaml. Each item: {query, locations, limit, filters}"
    )


class ScrapeStatusResponse(BaseModel):
    run_id: str
    status: str                         # running | completed | failed
    jobs_found: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


# ── Jobs ──────────────────────────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    semantic: Optional[float] = None
    skills: Optional[float] = None
    experience: Optional[float] = None
    title: Optional[float] = None


class JobResponse(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str] = None
    date_posted: Optional[str] = None
    link: str
    apply_link: Optional[str] = None
    company_link: Optional[str] = None
    description: Optional[str] = None
    insights: Optional[list] = None
    # Parsed fields
    skills_required: Optional[list[str]] = None
    skills_nice_to_have: Optional[list[str]] = None
    experience_years: Optional[str] = None
    experience_years_min: Optional[int] = None
    seniority_level: Optional[str] = None
    employment_type: Optional[str] = None
    remote_policy: Optional[str] = None
    salary_range: Optional[str] = None
    # Match fields
    match_score: Optional[float] = None
    matched_skills: Optional[list[str]] = None
    missing_skills: Optional[list[str]] = None
    score_breakdown: Optional[ScoreBreakdown] = None
    # Tracking
    status: str = "new"
    scraped_at: Optional[datetime] = None


class StatusUpdateRequest(BaseModel):
    status: str = Field(
        ...,
        pattern="^(new|saved|applied|interview|offer|rejected)$",
        description="Application tracking status"
    )


class StatusUpdateResponse(BaseModel):
    job_id: str
    status: str
    updated: bool


# ── Resume ────────────────────────────────────────────────────────────────────

class ResumeUploadResponse(BaseModel):
    resume_id: str
    filename: str
    characters_extracted: int
    preview: str                        # first 200 chars of extracted text
    message: str


class ResumeParseRequest(BaseModel):
    resume_id: str


class ResumeParseResponse(BaseModel):
    resume_id: str
    profile: dict                       # ParsedResume.model_dump()


# ── Match ─────────────────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    resume_id: Optional[str] = Field(
        None,
        description="Resume DB ID. If omitted, the active resume is used."
    )
    force_reparse: bool = Field(
        False,
        description="Re-parse JDs even if already cached in DB"
    )


class SkillGap(BaseModel):
    skill: str
    frequency: int
    pct_jobs: float


class MatchResponse(BaseModel):
    resume_id: str
    total_jobs: int
    scored_jobs: list[JobResponse]
    skill_gaps: list[SkillGap]
    errors: list[str] = Field(default_factory=list)


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    db: str
    version: str = "0.1.0"


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    error_type: Optional[str] = None
