"""
Shared FastAPI dependencies — injected via Depends().

Phase 4.
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from db.repository import AsyncJobRepository


async def get_repo(db: AsyncSession = Depends(get_db)) -> AsyncJobRepository:
    """Inject a ready AsyncJobRepository into any route."""
    return AsyncJobRepository(db)
