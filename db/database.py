"""Async DB engine + session factory."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from config.settings import get_settings
from db.models import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add new columns to existing DBs (SQLite ignores if already present via try/except)
        for stmt in [
            "ALTER TABLE jobs ADD COLUMN scored_with_resume_id VARCHAR(36)",
        ]:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception:
                pass  # column already exists

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
