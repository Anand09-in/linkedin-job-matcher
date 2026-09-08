"""
Phase 1 test infrastructure — plan.md: "integration tests against a real
(containerized, ephemeral) Postgres." Runs inside the `worker`/`api` image on
the Compose network (Postgres has no host-published port, by design), against
a dedicated `job_matcher_test` database that's dropped and recreated fresh at
the start of the session and dropped again at the end.

Repository methods call session.commit() internally, so per-test isolation
is done by truncating all domain tables after each test rather than relying
on a rollback-only outer transaction.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

TEST_DB_NAME = "job_matcher_test"


def _to_asyncpg_dsn(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


async def _drop_and_create_test_db(maintenance_url: str) -> None:
    conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(maintenance_url))
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_test_db(maintenance_url: str) -> None:
    conn = await asyncpg.connect(dsn=_to_asyncpg_dsn(maintenance_url))
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def _use_test_database():
    from app.core.config import get_settings

    base_url = get_settings().database_url  # postgresql+asyncpg://user:pass@postgres:5432/job_matcher
    root_url, _, _ = base_url.rpartition("/")
    maintenance_url = f"{root_url}/postgres"
    test_url = f"{root_url}/{TEST_DB_NAME}"

    asyncio.run(_drop_and_create_test_db(maintenance_url))

    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")

    yield

    asyncio.run(_drop_test_db(maintenance_url))


@pytest_asyncio.fixture
async def db_session():
    from app.core.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        yield session

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE jobs, rejected_jobs, scrape_runs, pipelines, "
                "resumes, llm_settings, feature_results, scraper_credentials RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(db_session):
    from app.domain.repository import Repository

    return Repository(db_session)


class _SessionCtx:
    """Wraps an already-open test session as an async context manager, so
    `async with AsyncSessionLocal() as session:` inside app code under test
    reuses the SAME session/transaction db_session is using — otherwise it
    would open a second real connection bound to whatever DATABASE_URL
    app.domain.db.engine was constructed with at first import (which can
    happen before this session's env-var patch, if another test module
    imports it transitively at collection time — see test_salary_lookup_task
    for the same pattern). Used via `patch(..., return_value=_SessionCtx(...))`."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _FakeArqRedis:
    """Records enqueue_job calls instead of touching real Redis — used as
    `app.state.redis` in api_client so POST /scrape doesn't require (or
    accidentally feed jobs to) the real arq worker process during tests."""

    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, task_name: str, *args):
        self.enqueued.append((task_name, *args))
        return type("FakeArqJob", (), {"job_id": "fake-job-id"})()

    async def ping(self):
        return True


@pytest_asyncio.fixture
async def api_client(db_session):
    """An httpx.AsyncClient wired directly to the FastAPI app via ASGI
    transport (no real network, no lifespan — app.state.redis is set
    manually to the fake above instead of lifespan's real create_pool)."""
    from unittest.mock import AsyncMock, patch

    import httpx

    from app.llm_tasks.schemas import ResumeProfile
    from app.main import app

    app.state.redis = _FakeArqRedis()

    # A default fake for POST/PUT /resumes' eager parse-at-upload-time call
    # (app/api/routes/resumes.py's _parse_and_cache) — without this, any
    # test that uploads a resume would trigger a REAL Bedrock call via
    # parse_resume(). Patched at its source module (app.llm_tasks.
    # resume_parser), not app.api.routes.resumes, since _parse_and_cache
    # does `from app.llm_tasks.resume_parser import parse_resume` freshly
    # INSIDE the function on every call — same lazy-import-respects-
    # source-patch pattern as the AsyncSessionLocal patches below. A test
    # that cares about the actual parsed content re-patches this itself
    # with a more specific fake; unittest.mock.patch nests correctly.
    fake_profile = ResumeProfile(summary="Test summary", skills=["Python"], current_title="Engineer", total_experience_years=2.0)

    # Two separate patches, not one: app.api.dependencies imports
    # AsyncSessionLocal at ITS OWN module top level (bound once, at import
    # time, into that module's namespace — patching app.domain.db later
    # wouldn't reach it), while app.core.llm's _get_active_llm_setting()
    # does `from app.domain.db import AsyncSessionLocal` freshly INSIDE the
    # function on every call (a lazy import that re-reads whatever
    # app.domain.db.AsyncSessionLocal currently is) — so routes that call
    # get_llm() (features.py) need the second patch too, or they'd silently
    # read/write the real dev database's LLMSetting row during a test.
    with patch("app.api.dependencies.AsyncSessionLocal", return_value=_SessionCtx(db_session)), \
         patch("app.domain.db.AsyncSessionLocal", return_value=_SessionCtx(db_session)), \
         patch("app.llm_tasks.resume_parser.parse_resume", AsyncMock(return_value=fake_profile)):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
