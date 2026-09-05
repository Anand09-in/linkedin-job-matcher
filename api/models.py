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


class BulkDeleteResponse(BaseModel):
    deleted_count: int
    before_date: str


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


# ── Phase 6 Feature responses ─────────────────────────────────────────────────

class CoverLetterResponse(BaseModel):
    job_id: str
    job_title: str
    company: str
    cover_letter: str
    tone: str
    word_count: int
    cached: bool = False


class ATSComponentScores(BaseModel):
    keyword_density: float
    title_word_presence: float
    section_coverage: float
    quantified_achievements: float


class ATSResponse(BaseModel):
    job_id: str
    resume_id: str
    overall_score: float
    components: ATSComponentScores
    matched_keywords: list[str]
    missing_keywords: list[str]
    matched_title_words: list[str]
    missing_title_words: list[str]
    detected_sections: list[str]
    quant_count: int
    predicted_pass: bool
    tips: list[str]


class InterviewQuestion(BaseModel):
    category: str
    question: str
    answer_framework: str
    key_points: list[str]


class InterviewPrepResponse(BaseModel):
    job_id: str
    job_title: str
    company: str
    questions: list[InterviewQuestion]
    prep_tips: list[str]


class SalaryRangeResponse(BaseModel):
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    currency: str = "USD"
    period: str = "annual"
    raw_text: Optional[str] = None


class SalaryBenchmarkResponse(BaseModel):
    job_id: str
    job_title: str
    location: Optional[str]
    currency: str
    extracted_salary: Optional[SalaryRangeResponse]
    market_low: float
    market_mid: float
    market_high: float
    your_likely_band: str
    negotiation_tips: list[str]
    benefits_to_ask: list[str]
    notes: list[str]


class CompanyResearchResponse(BaseModel):
    job_id: str
    company: str
    location: Optional[str]
    seniority_hint: Optional[str]
    employment_type: Optional[str]
    job_function: Optional[str]
    industry: Optional[str]
    remote_policy: Optional[str]
    salary_hint: Optional[str]
    domain: Optional[str]
    size_hint: Optional[str]
    tech_stack_hints: list[str]
    culture_signals: list[str]
    green_flags: list[str]
    red_flags: list[str]
    overall_impression: str


class TrackerStatsResponse(BaseModel):
    total_saved: int
    total_applied: int
    total_interviews: int
    total_offers: int
    total_rejected: int
    apply_to_interview_rate: float
    interview_to_offer_rate: float


class LearningItemResponse(BaseModel):
    skill: str
    why: str
    estimated_weeks: int
    resources: list[str]


class TimeHorizonResponse(BaseModel):
    horizon: str
    label: str
    roles: list[str]
    action_items: list[str]


class CareerPathResponse(BaseModel):
    current_title: str
    total_exp_years: float
    horizons: list[TimeHorizonResponse]
    learning_roadmap: list[LearningItemResponse]
    summary: str


class WebSnippetResponse(BaseModel):
    title: str
    body: str
    url: str = ""


class CompanyIntelResponse(BaseModel):
    job_id: str
    company: str
    location: Optional[str]
    seniority_hint: Optional[str]
    employment_type: Optional[str]
    job_function: Optional[str]
    industry: Optional[str]
    remote_policy: Optional[str]
    domain: Optional[str]
    size_hint: Optional[str]
    tech_stack_hints: list[str]
    culture_signals: list[str]
    green_flags: list[str]
    red_flags: list[str]
    overall_impression: str
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_currency: str
    salary_period: str
    salary_source: str
    market_low: float
    market_mid: float
    market_high: float
    your_likely_band: str
    negotiation_tips: list[str]
    benefits_to_ask: list[str]
    web_search_used: bool
    search_query: str = ""
    search_snippets: list[WebSnippetResponse] = []


class ResumeSuggestionResponse(BaseModel):
    section: str
    priority: str
    issue: str
    suggestion: str
    example: Optional[str] = None


class ResumeImprovementResponse(BaseModel):
    job_id: str
    job_title: str
    company: str
    overall_fit_grade: str
    suggestions: list[ResumeSuggestionResponse]
    keywords_to_add: list[str]
    summary_rewrite: str
    top_actions: list[str]
