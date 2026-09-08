"""
Pydantic request/response models for the Phase 7 API surface
(architecture.md §3.4). Every route returns one of these — no bare `dict`/
ORM-object returns left over from the Phase 0-6 `/debug/*` prototyping.

Response models set `model_config = ConfigDict(from_attributes=True)` so a
route can do `JobResponse.model_validate(job)` directly against the
SQLAlchemy row — v2's ORM field names already match what the API exposes
1:1 (unlike v1, where `api/routes/jobs.py` had to hand-map every field), so
there's no `_job_to_response()`-style translation function to maintain here.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Jobs ─────────────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company: str
    location: Optional[str]
    link: str
    apply_link: Optional[str]
    description: Optional[str]
    skills_required: Optional[list[str]]
    skills_nice_to_have: Optional[list[str]]
    experience_years_min: Optional[int]
    seniority_level: Optional[str]
    employment_type: Optional[str]
    remote_policy: Optional[str]
    education_required: Optional[str]
    match_score: Optional[float]
    matched_skills: Optional[list[str]]
    missing_skills: Optional[list[str]]
    match_rationale: Optional[str]
    scored_with_resume_id: Optional[uuid.UUID]
    pipeline_id: uuid.UUID
    scrape_run_id: Optional[uuid.UUID]
    source_site: str
    status: str
    salary_benchmark: Optional[dict[str, Any]]
    salary_enrichment_status: str
    date_posted: Optional[datetime]
    scraped_at: datetime
    updated_at: Optional[datetime]


class JobStatusUpdateRequest(BaseModel):
    status: str = Field(..., description="new | saved | applied | interview | offer | rejected")


class JobStatusUpdateResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    updated: bool


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    before_date: str


class JobCountResponse(BaseModel):
    count: int
    before_date: str


class JobStatsResponse(BaseModel):
    total_jobs: int
    with_description: int
    with_match_score: int
    avg_match_score: float


# ── Resumes (FR-1A.2) ────────────────────────────────────────────────────────

class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    filename: str
    parsed_profile: Optional[dict[str, Any]]
    uploaded_at: datetime


class ResumeDetailResponse(ResumeResponse):
    """Includes raw_text — omitted from the list response since it can run
    to thousands of characters and the list view never needs it."""

    raw_text: str


# ── Pipelines (FR-1A.1) ──────────────────────────────────────────────────────

class PipelineCreateRequest(BaseModel):
    name: str
    site: str
    query: str
    locations: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    resume_id: Optional[uuid.UUID] = None
    batch_size: int = 5
    min_match_score_override: Optional[float] = None
    max_experience_years_override: Optional[int] = None
    enabled: bool = True
    schedule_cron: Optional[str] = None


class PipelineUpdateRequest(BaseModel):
    """All fields optional — only what's provided gets updated
    (Repository.update_pipeline is already a partial update)."""

    name: Optional[str] = None
    site: Optional[str] = None
    query: Optional[str] = None
    locations: Optional[list[str]] = None
    filters: Optional[dict[str, Any]] = None
    resume_id: Optional[uuid.UUID] = None
    batch_size: Optional[int] = None
    min_match_score_override: Optional[float] = None
    max_experience_years_override: Optional[int] = None
    enabled: Optional[bool] = None
    schedule_cron: Optional[str] = None


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    resume_id: Optional[uuid.UUID]
    site: str
    query: str
    locations: list
    filters: dict[str, Any]
    batch_size: int
    min_match_score_override: Optional[float]
    max_experience_years_override: Optional[int]
    enabled: bool
    schedule_cron: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]


class RejectedJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scrape_run_id: uuid.UUID
    pipeline_id: uuid.UUID
    title: str
    company: str
    link: str
    match_score: Optional[float]
    reason: str
    created_at: datetime


# ── Scrape (FR-1A.6) ─────────────────────────────────────────────────────────

class ScrapeTriggerRequest(BaseModel):
    pipeline_id: uuid.UUID
    limit: Optional[int] = Field(None, description="Cap the number of raw jobs scraped, for manual testing")


class ScrapeTriggerResponse(BaseModel):
    enqueued: bool
    job_id: str
    pipeline_id: uuid.UUID


class DeletedCountResponse(BaseModel):
    deleted_count: int


class ScrapeRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pipeline_id: uuid.UUID
    status: str
    cancel_requested: bool
    config_snapshot: dict[str, Any]
    jobs_seen: int
    jobs_saved: int
    jobs_rejected: int
    errors: list
    started_at: datetime
    finished_at: Optional[datetime]


# ── LLM settings (FR-3.1/3.2 — moved here unchanged from Phase 5's main.py) ──

class LLMSettingResponse(BaseModel):
    provider: str
    model: str
    temperature: float
    max_tokens: int


class LLMSettingUpdateRequest(BaseModel):
    provider: str = "bedrock"
    model: str
    temperature: float = 0.1
    max_tokens: int = 2000


# ── Scraper credentials (Phase 8 — UI-editable, e.g. LinkedIn's li_at cookie) ─

class ScraperCredentialResponse(BaseModel):
    site: str
    configured: bool = Field(..., description="Whether a value has been set — the value itself is never echoed back.")
    last_check_status: Optional[str] = Field(None, description="'valid' | 'invalid' | 'error' | null if never checked.")
    last_checked_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScraperCredentialUpdateRequest(BaseModel):
    value: str = Field(..., min_length=1)


class ScraperCredentialCheckResponse(BaseModel):
    enqueued: bool
    job_id: str
    site: str


# ── On-demand features (FR-6 — moved here unchanged from Phase 6's main.py) ──

class FeatureRequestBody(BaseModel):
    tone: Optional[str] = None
    channel: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    regenerate: bool = False


class FeatureRunResponse(BaseModel):
    feature: str
    job_id: str
    params: dict[str, Any]
    cached: bool
    result: dict[str, Any]
