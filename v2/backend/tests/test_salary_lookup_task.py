"""
Integration tests for salary_lookup_task against real Postgres (via
conftest's `repo` fixture) — get_salary_benchmark mocked so no real web
search/Bedrock call happens. Exercises FR-5.3/5.4: a failure never touches
the job's match_score/status, and the task is idempotent by job_id.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from app.llm_tasks.schemas import SalaryBenchmark
from app.workers.tasks import salary_lookup_task


async def _make_job(repo, pipeline, match_score=0.9):
    job, _ = await repo.upsert_job(
        {
            "title": "Data Engineer",
            "company": "Acme",
            "location": "Bangalore, India",
            "link": f"https://x/{uuid.uuid4()}",
            "pipeline_id": pipeline.id,
            "source_site": pipeline.site,
            "match_score": match_score,
        }
    )
    return job


async def _make_pipeline(repo):
    resume = await repo.create_resume(name="R", filename="r.txt", raw_text="resume text")
    return await repo.create_pipeline(name="P", site="linkedin", query="Engineer", resume_id=resume.id)


async def test_salary_lookup_task_persists_benchmark(repo, db_session):
    pipeline = await _make_pipeline(repo)
    job = await _make_job(repo, pipeline)
    fake_benchmark = SalaryBenchmark(min_amount=1200000, max_amount=1800000, currency="INR", confidence="medium", source_note="test")

    with patch("app.workers.tasks.AsyncSessionLocal", return_value=_SessionCtx(db_session)), \
         patch("app.workers.tasks.get_llm", return_value=object()), \
         patch("app.workers.tasks.get_salary_benchmark", AsyncMock(return_value=fake_benchmark)):
        result = await salary_lookup_task(ctx={}, job_id=str(job.id))

    assert result["status"] == "done"
    updated = await repo.get_job(job.id)
    assert updated.salary_benchmark["min_amount"] == 1200000
    assert updated.salary_enrichment_status == "done"
    # Never touched — FR-5.3, a salary lookup can't affect job visibility/filtering.
    assert updated.match_score == 0.9


async def test_salary_lookup_task_failure_does_not_touch_match_score(repo, db_session):
    """FR-5.3: a failed lookup only marks salary_enrichment_status="failed" —
    it must never fail/roll back the job itself."""
    pipeline = await _make_pipeline(repo)
    job = await _make_job(repo, pipeline)

    with patch("app.workers.tasks.AsyncSessionLocal", return_value=_SessionCtx(db_session)), \
         patch("app.workers.tasks.get_llm", return_value=object()), \
         patch("app.workers.tasks.get_salary_benchmark", AsyncMock(side_effect=RuntimeError("simulated search failure"))):
        result = await salary_lookup_task(ctx={}, job_id=str(job.id))

    assert result["status"] == "failed"
    updated = await repo.get_job(job.id)
    assert updated.salary_enrichment_status == "failed"
    assert updated.match_score == 0.9  # untouched


async def test_salary_lookup_task_is_idempotent(repo, db_session):
    """FR-5.4: running it twice for the same job just overwrites with the
    same or refreshed data — safe under arq's at-least-once delivery."""
    pipeline = await _make_pipeline(repo)
    job = await _make_job(repo, pipeline)
    fake_benchmark = SalaryBenchmark(min_amount=1000000, max_amount=1500000, confidence="low", source_note="test", currency="INR")

    with patch("app.workers.tasks.AsyncSessionLocal", return_value=_SessionCtx(db_session)), \
         patch("app.workers.tasks.get_llm", return_value=object()), \
         patch("app.workers.tasks.get_salary_benchmark", AsyncMock(return_value=fake_benchmark)):
        await salary_lookup_task(ctx={}, job_id=str(job.id))
        await salary_lookup_task(ctx={}, job_id=str(job.id))

    updated = await repo.get_job(job.id)
    assert updated.salary_benchmark["min_amount"] == 1000000


class _SessionCtx:
    """Wraps an already-open test session as an async context manager, so
    `async with AsyncSessionLocal() as session:` in the task under test
    reuses the SAME session/transaction the `repo` fixture is using —
    otherwise the task would open a second real connection the test
    couldn't see writes from without a commit/refresh round trip. Used via
    `patch(..., return_value=_SessionCtx(db_session))`, so the patched
    AsyncSessionLocal() call returns this instance directly."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False
