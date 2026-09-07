"""
SQLAlchemy ORM models.

Phase 0 note: SystemPing is a throwaway table that exists ONLY to prove the
api/worker/redis/postgres wiring end to end (plan.md Phase 0 exit criteria —
"the trivial task completes and its result is visible in Postgres"). It is not
part of the real domain model. Phase 1 replaces/supplements this file with
Job, Resume, Pipeline, ScrapeRun, RejectedJob, LLMSetting per architecture.md
§3.2 — this file is deliberately minimal until then.

Per FR-4.4, schema changes go through Alembic migrations, never
Base.metadata.create_all() at app startup (that was v1's approach and is
explicitly what v2 moves away from).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SystemPing(Base):
    """Phase 0 wiring-check table — see module docstring."""

    __tablename__ = "system_ping"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
