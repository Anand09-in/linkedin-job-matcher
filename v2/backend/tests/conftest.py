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
                "resumes, llm_settings RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()


@pytest_asyncio.fixture
async def repo(db_session):
    from app.domain.repository import Repository

    return Repository(db_session)
