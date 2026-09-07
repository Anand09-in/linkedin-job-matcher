"""domain schema: resumes, pipelines, scrape_runs, jobs, rejected_jobs, llm_settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── resumes (FR-1A.2 — no is_active flag) ────────────────────────────────
    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("parsed_profile", postgresql.JSONB(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── pipelines (FR-1A.1) ───────────────────────────────────────────────────
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("site", sa.String(100), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("locations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("filters", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("min_match_score_override", sa.Float(), nullable=True),
        sa.Column("max_experience_years_override", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("schedule_cron", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pipelines_resume_id", "pipelines", ["resume_id"])

    # ── scrape_runs ───────────────────────────────────────────────────────────
    op.create_table(
        "scrape_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="running"),
        sa.Column("config_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("jobs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scrape_runs_pipeline_id", "scrape_runs", ["pipeline_id"])

    # ── jobs ──────────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("apply_link", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("skills_required", postgresql.JSONB(), nullable=True),
        sa.Column("skills_nice_to_have", postgresql.JSONB(), nullable=True),
        sa.Column("experience_years_min", sa.Integer(), nullable=True),
        sa.Column("seniority_level", sa.String(100), nullable=True),
        sa.Column("employment_type", sa.String(100), nullable=True),
        sa.Column("remote_policy", sa.String(100), nullable=True),
        sa.Column("education_required", sa.String(255), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("matched_skills", postgresql.JSONB(), nullable=True),
        sa.Column("missing_skills", postgresql.JSONB(), nullable=True),
        sa.Column("match_rationale", sa.Text(), nullable=True),
        sa.Column("scored_with_resume_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scrape_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_site", sa.String(100), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="new"),
        sa.Column("salary_benchmark", postgresql.JSONB(), nullable=True),
        sa.Column("salary_enrichment_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("date_posted", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_jobs_link", "jobs", ["link"])
    op.create_index("ix_jobs_link", "jobs", ["link"])
    op.create_index("ix_jobs_pipeline_id", "jobs", ["pipeline_id"])
    op.create_index("ix_jobs_scrape_run_id", "jobs", ["scrape_run_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_match_score", "jobs", ["match_score"])
    op.create_index("ix_jobs_date_posted", "jobs", ["date_posted"])

    # ── rejected_jobs (FR-2.3) ────────────────────────────────────────────────
    op.create_table(
        "rejected_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scrape_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scrape_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipelines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rejected_jobs_scrape_run_id", "rejected_jobs", ["scrape_run_id"])
    op.create_index("ix_rejected_jobs_pipeline_id", "rejected_jobs", ["pipeline_id"])

    # ── llm_settings (FR-3.1 — single active row, global) ────────────────────
    op.create_table(
        "llm_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.1"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("llm_settings")
    op.drop_table("rejected_jobs")
    op.drop_table("jobs")
    op.drop_table("scrape_runs")
    op.drop_table("pipelines")
    op.drop_table("resumes")
