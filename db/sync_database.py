"""
Synchronous SQLAlchemy engine — used ONLY by the scraper thread.
FastAPI uses the async engine in database.py.

Both point to the same SQLite file; SQLite handles concurrent writes fine
for our single-writer use case.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db.models import Base

settings = get_settings()

# Convert async URL → sync URL  (remove "+aiosqlite")
_sync_url = settings.database_url.replace("+aiosqlite", "")

sync_engine = create_engine(
    _sync_url,
    connect_args={"check_same_thread": False},  # safe — we serialise writes with a lock
    echo=False,
)

SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


def init_sync_db() -> None:
    """Create tables synchronously — used by CLI runner and tests."""
    Base.metadata.create_all(bind=sync_engine)


def get_sync_db() -> Session:
    """Return a plain Session. Caller is responsible for .close()."""
    return SyncSessionLocal()
