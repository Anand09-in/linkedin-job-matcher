"""
SQLAlchemy ORM models — single source of truth for the DB schema.

Phase 1: Job, Resume, ScrapeRun tables.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ── Raw scraped fields (captured from EventData) ──────────────────────────
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_posted: Mapped[str | None] = mapped_column(String(100), nullable=True)
    link: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False, index=True)
    apply_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    company_link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # insights[0] = seniority, [1] = employment type, [2] = job function, [3] = industry
    insights: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Parsed / enriched fields (filled by JD parser node in Phase 2) ────────
    skills_required: Mapped[list | None] = mapped_column(JSON, nullable=True)
    skills_nice_to_have: Mapped[list | None] = mapped_column(JSON, nullable=True)
    experience_years: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experience_years_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seniority_level: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_policy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    education_required: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Match scores (filled by matcher node in Phase 3) ──────────────────────
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)
    missing_skills: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Application tracking ──────────────────────────────────────────────────
    # Status flow: new → saved → applied → interview → offer / rejected
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)

    # ── Metadata ──────────────────────────────────────────────────────────────
    scraped_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "date_posted": self.date_posted,
            "link": self.link,
            "apply_link": self.apply_link,
            "company_link": self.company_link,
            "description": self.description,
            "description_html": self.description_html,
            "insights": self.insights,
            "skills_required": self.skills_required,
            "skills_nice_to_have": self.skills_nice_to_have,
            "experience_years": self.experience_years,
            "experience_years_min": self.experience_years_min,
            "seniority_level": self.seniority_level,
            "employment_type": self.employment_type,
            "remote_policy": self.remote_policy,
            "match_score": self.match_score,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "status": self.status,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
        }


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured profile extracted by ResumeParser (Phase 2)
    parsed_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(50), default="running", nullable=False)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
