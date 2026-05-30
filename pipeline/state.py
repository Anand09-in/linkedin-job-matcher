"""
LangGraph pipeline state schema.

All nodes read from and write to this TypedDict.
Each node returns a partial dict — LangGraph merges them automatically.

Phase 3.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional
from typing_extensions import TypedDict


class JobScore(TypedDict, total=False):
    """Scoring breakdown for a single job."""
    job_id: str
    match_score: float                  # 0.0 – 1.0 overall weighted score
    semantic_score: float               # embedding cosine similarity
    skills_score: float                 # required skills overlap ratio
    experience_score: float             # experience alignment score
    title_score: float                  # job title ↔ candidate title similarity
    matched_skills: list[str]           # skills candidate has
    missing_skills: list[str]           # required skills candidate lacks


class PipelineState(TypedDict, total=False):
    # ── Input ────────────────────────────────────────────────────────────────
    resume_id: str                      # DB Resume.id — set before invoking graph
    resume_text: str                    # raw extracted text from PDF

    # ── Scraper node output ───────────────────────────────────────────────────
    raw_jobs: list[dict]                # list of scraped job dicts (from DB or live)
    run_id: str                         # ScrapeRun.id

    # ── JD parser node output ─────────────────────────────────────────────────
    parsed_jobs: list[dict]             # raw_jobs enriched with skills/exp/level fields

    # ── Resume parser node output ─────────────────────────────────────────────
    candidate_profile: dict             # ParsedResume.model_dump()

    # ── Matcher node output ───────────────────────────────────────────────────
    scored_jobs: list[dict]             # parsed_jobs enriched with match_score fields
    skill_gaps: list[dict]              # [{skill, frequency, jobs_needing}]

    # ── Feature node outputs (Phase 6) ────────────────────────────────────────
    cover_letters: dict                 # job_id → cover letter text
    ats_scores: dict                    # job_id → {score, keywords}
    interview_questions: dict           # job_id → [questions]

    # ── Control ───────────────────────────────────────────────────────────────
    errors: Annotated[list[str], operator.add]  # merged across parallel nodes
