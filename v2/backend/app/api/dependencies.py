"""
Shared FastAPI dependencies — Phase 7's real routers all use this instead of
each opening its own `async with AsyncSessionLocal()` block (the pattern
main.py's debug endpoints used, fine for a handful of one-off endpoints but
not worth repeating across a real, multi-router API surface).
"""
from __future__ import annotations

from typing import AsyncIterator

from app.domain.db import AsyncSessionLocal
from app.domain.repository import Repository


async def get_repo() -> AsyncIterator[Repository]:
    async with AsyncSessionLocal() as session:
        yield Repository(session)
