"""
SQLAlchemy ORM models — architecture.md §3.2.

Phase 0 left a throwaway SystemPing table to prove container wiring; it stays
(main.py's /debug endpoints still use it) but is not part of the real domain.

Phase 1 domain model, per FR-1A / FR-2 / FR-4 / FR-5:
    Resume    — multiple, no "active" flag (FR-1A.2). Bound to pipelines, not
                globally selected.
    Pipeline  — a named, independently runnable {resume, site, query, filters,
                thresholds} bundle (FR-1A.1). resume_id is nullable (FR-2.6:
                extract-only mode with no resume bound).
    ScrapeRun — one run of one pipeline.
    Job       — a saved (i.e. filter-passing) posting, tagged with the
                pipeline/resume/run that produced it.
    RejectedJob — lightweight audit row for postings that failed the filter
                (FR-2.3) — never a full Job row.
    LLMSetting — single active row, global across all pipelines (FR-3.1,
                decisions log #8 in system-design.md).

Per FR-4.4, schema changes go through Alembic migrations, never
Base.metadata.create_all() at app startup.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0 — wiring-check only, not real domain (see module docstring)
# ─────────────────────────────────────────────────────────────────────────────

class SystemPing(Base):
    __tablename__ = "system_ping"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScrapeDebugBatch(Base):
    """
    Phase 2 wiring-check table — same spirit as SystemPing: proves a real
    adapter run (worker -> Playwright/site -> Redis -> Postgres) produces
    correct raw batches, WITHOUT touching the real Job table (that's Phase
    3's job: extraction+filtering decides what becomes a Job). Removed once
    Phase 3's real scrape_service.py lands.
    """

    __tablename__ = "scrape_debug_batches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    pipeline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    jobs: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# Resume — FR-1A.2: multiple, no "active" flag
# ─────────────────────────────────────────────────────────────────────────────

class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pipelines: Mapped[list["Pipeline"]] = relationship(back_populates="resume")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline — FR-1A.1: named, independently runnable, resume-bound (or not)
# ─────────────────────────────────────────────────────────────────────────────

class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Nullable: FR-2.6 "extract-only" pipelines with no resume bound.
    #
    # ondelete=SET NULL (not RESTRICT): the app-level guard in
    # Repository.delete_resume() (FR-1A.7) only blocks deletion while an
    # ENABLED pipeline references the resume — a disabled pipeline should not
    # keep blocking it. RESTRICT would enforce that at the DB level too
    # regardless of `enabled`, since the FK itself doesn't know about that
    # column; SET NULL lets a disabled pipeline's resume_id null out
    # automatically (falling back to FR-2.6 extract-only mode) once the
    # resume it pointed at is actually deleted.
    resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )

    site: Mapped[str] = mapped_column(String(100), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    locations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # FR-1A.4: per-pipeline override, falls back to a system default when null.
    min_match_score_override: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_experience_years_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    resume: Mapped[Resume | None] = relationship(back_populates="pipelines")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="pipeline")


# ─────────────────────────────────────────────────────────────────────────────
# ScrapeRun — one run of one pipeline
# ─────────────────────────────────────────────────────────────────────────────

class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running")
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    jobs_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_saved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pipeline: Mapped[Pipeline] = relationship(back_populates="scrape_runs")


# ─────────────────────────────────────────────────────────────────────────────
# Job — a saved, filter-passing posting
# ─────────────────────────────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    apply_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Extracted fields (FR-2.1) ────────────────────────────────────────────
    skills_required: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    skills_nice_to_have: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    experience_years_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    education_required: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Match fields (FR-2.2) ─────────────────────────────────────────────────
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    matched_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    missing_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    match_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_with_resume_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True
    )

    # ── Pipeline / run attribution (FR-1A.6) ─────────────────────────────────
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scrape_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_site: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── Tracking (status flow: new -> saved -> applied -> interview -> offer/rejected,
    #    plus "deleted" for the soft-delete carried over from v1) ────────────
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="new", index=True)

    # ── Salary enrichment (FR-5) ──────────────────────────────────────────────
    salary_benchmark: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    salary_enrichment_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    # ── Metadata ──────────────────────────────────────────────────────────────
    # Real timestamptz now (architecture.md §3.2 note) — v1 had this as free
    # text and it silently ended up empty for every job; nullable here because
    # a source site may still fail to surface a posted date, but the FALLBACK
    # for bulk-delete-by-date now compares real timestamps, not a text prefix.
    date_posted: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# RejectedJob — lightweight audit row (FR-2.3)
# ─────────────────────────────────────────────────────────────────────────────

class RejectedJob(Base):
    __tablename__ = "rejected_jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    scrape_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    link: Mapped[str] = mapped_column(Text, nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────────────────────────────────────
# LLMSetting — single active row, global (FR-3.1)
# ─────────────────────────────────────────────────────────────────────────────

class LLMSetting(Base):
    __tablename__ = "llm_settings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
