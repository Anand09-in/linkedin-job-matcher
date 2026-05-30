"""Pydantic v2 request/response models for the FastAPI layer."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ScrapeRequest(BaseModel):
    query_overrides: Optional[dict] = None   # optional per-request config overrides


class ScrapeStatusResponse(BaseModel):
    run_id: str
    status: str
    jobs_found: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class JobResponse(BaseModel):
    id: str
    title: str
    company: str
    location: Optional[str]
    date_posted: Optional[str]
    link: str
    apply_link: Optional[str]
    description: Optional[str]
    skills_required: Optional[list[str]]
    experience_years: Optional[str]
    seniority_level: Optional[str]
    match_score: Optional[float]
    matched_skills: Optional[list[str]]
    missing_skills: Optional[list[str]]
    status: str
    scraped_at: datetime


class MatchRequest(BaseModel):
    resume_id: str
    job_ids: Optional[list[str]] = None   # None = match against all jobs


class MatchResponse(BaseModel):
    resume_id: str
    scored_jobs: list[JobResponse]
    skill_gaps: Optional[list[dict]] = None


class ResumeUploadResponse(BaseModel):
    resume_id: str
    filename: str
    skills_detected: Optional[list[str]] = None


class StatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern="^(new|saved|applied|interview|offer|rejected)$")
