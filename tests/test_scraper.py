"""
Phase 1 tests for ScraperService and SyncJobRepository.

Run with:
    pytest tests/test_scraper.py -v

No LinkedIn account needed — all tests use mock EventData.
"""
from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from db.models import Base, Job, ScrapeRun
from db.repository import SyncJobRepository


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def in_memory_engine():
    """Fresh SQLite in-memory engine per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def sync_session(in_memory_engine):
    """Sync session bound to the in-memory engine."""
    Session = sessionmaker(bind=in_memory_engine)
    with Session() as session:
        yield session


@pytest.fixture()
def repo(sync_session):
    return SyncJobRepository(sync_session)


def make_mock_event_data(**overrides) -> MagicMock:
    """Build a realistic mock EventData object."""
    data = MagicMock()
    data.title = overrides.get("title", "Machine Learning Engineer")
    data.company = overrides.get("company", "Acme Corp")
    data.place = overrides.get("location", "Bangalore, India")
    data.location = overrides.get("location", "Bangalore, India")
    data.date = overrides.get("date", "2024-06-01")
    data.link = overrides.get("link", f"https://linkedin.com/jobs/view/{uuid.uuid4()}")
    data.apply_link = overrides.get("apply_link", "https://acme.com/apply")
    data.company_link = overrides.get("company_link", "https://linkedin.com/company/acme")
    data.description = overrides.get(
        "description",
        "We are looking for an ML Engineer with 3+ years experience in Python, TensorFlow, PyTorch. "
        "Strong knowledge of LLMs, transformers, and MLOps required."
    )
    data.description_html = overrides.get("description_html", f"<p>{data.description}</p>")
    data.insights = overrides.get("insights", ["Mid-Senior level", "Full-time", "Engineering", "Technology"])
    return data


# ─────────────────────────────────────────────────────────────────────────────
# SyncJobRepository tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncJobRepository:

    def test_create_scrape_run(self, repo, sync_session):
        run_id = repo.create_scrape_run({"query": "test"})
        assert run_id
        run = sync_session.execute(select(ScrapeRun).where(ScrapeRun.id == run_id)).scalar_one()
        assert run.status == "running"
        assert run.jobs_found == 0
        assert run.config_snapshot == {"query": "test"}

    def test_finish_scrape_run_completed(self, repo, sync_session):
        run_id = repo.create_scrape_run({})
        repo.finish_scrape_run(run_id, jobs_found=42)
        run = sync_session.execute(select(ScrapeRun).where(ScrapeRun.id == run_id)).scalar_one()
        assert run.status == "completed"
        assert run.jobs_found == 42
        assert run.error is None
        assert run.finished_at is not None

    def test_finish_scrape_run_failed(self, repo, sync_session):
        run_id = repo.create_scrape_run({})
        repo.finish_scrape_run(run_id, jobs_found=5, error="429 Too Many Requests")
        run = sync_session.execute(select(ScrapeRun).where(ScrapeRun.id == run_id)).scalar_one()
        assert run.status == "failed"
        assert run.error == "429 Too Many Requests"

    def test_upsert_job_new(self, repo, sync_session):
        data = make_mock_event_data()
        job_dict = {
            "title": data.title,
            "company": data.company,
            "location": data.place,
            "date_posted": data.date,
            "link": data.link,
            "apply_link": data.apply_link,
            "company_link": data.company_link,
            "description": data.description,
            "description_html": data.description_html,
            "insights": list(data.insights),
        }
        job_id, is_new = repo.upsert_job(job_dict)
        assert is_new is True
        assert job_id

        job = sync_session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        assert job.title == "Machine Learning Engineer"
        assert job.company == "Acme Corp"
        assert job.description is not None
        assert len(job.description) > 0
        assert job.insights == ["Mid-Senior level", "Full-time", "Engineering", "Technology"]
        assert job.status == "new"

    def test_upsert_job_dedup_by_link(self, repo, sync_session):
        """Same link inserted twice should produce only one row (update, not insert)."""
        shared_link = "https://linkedin.com/jobs/view/12345"
        job_dict = {
            "title": "MLE",
            "company": "Acme",
            "link": shared_link,
            "description": "Original description",
            "insights": [],
        }
        _, is_new_1 = repo.upsert_job(job_dict)
        assert is_new_1 is True

        # Second upsert with updated description
        job_dict["description"] = "Updated description"
        _, is_new_2 = repo.upsert_job(job_dict)
        assert is_new_2 is False

        # Only one row in DB
        jobs = sync_session.execute(select(Job).where(Job.link == shared_link)).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].description == "Updated description"

    def test_upsert_job_skips_empty_link(self, repo):
        job_id, is_new = repo.upsert_job({"title": "No Link Job", "company": "X", "link": ""})
        assert job_id == ""
        assert is_new is False

    def test_bulk_upsert(self, repo, sync_session):
        jobs = [
            {"title": f"Job {i}", "company": "Co", "link": f"https://li.com/jobs/{i}", "insights": []}
            for i in range(5)
        ]
        new_count, updated_count = repo.bulk_upsert_jobs(jobs)
        assert new_count == 5
        assert updated_count == 0

        # Re-upsert same jobs — should all be updates
        new_count2, updated_count2 = repo.bulk_upsert_jobs(jobs)
        assert new_count2 == 0
        assert updated_count2 == 5

    def test_all_eventdata_fields_captured(self, repo, sync_session):
        """Verify every EventData field we care about makes it into the DB."""
        data = make_mock_event_data(
            title="Senior Data Scientist",
            company="DataCo",
            location="Mumbai, India",
            description="Need 5 years exp in Python, Spark, SQL",
            apply_link="https://dataco.com/apply/123",
            company_link="https://linkedin.com/company/dataco",
            insights=["Senior level", "Full-time", "Data Science", "Finance"],
        )
        job_dict = {
            "title": data.title,
            "company": data.company,
            "location": data.place,
            "date_posted": data.date,
            "link": data.link,
            "apply_link": data.apply_link,
            "company_link": data.company_link,
            "description": data.description,
            "description_html": data.description_html,
            "insights": list(data.insights),
        }
        job_id, _ = repo.upsert_job(job_dict)
        job = sync_session.execute(select(Job).where(Job.id == job_id)).scalar_one()

        assert job.title == "Senior Data Scientist"
        assert job.company == "DataCo"
        assert job.location == "Mumbai, India"
        assert job.apply_link == "https://dataco.com/apply/123"
        assert job.company_link == "https://linkedin.com/company/dataco"
        assert "Python" in job.description
        assert job.insights[0] == "Senior level"
        assert job.insights[3] == "Finance"


# ─────────────────────────────────────────────────────────────────────────────
# ScraperService unit tests (no real LinkedIn calls)
# ─────────────────────────────────────────────────────────────────────────────

class TestScraperService:

    def _make_service(self, monkeypatch) -> "ScraperService":
        """Create a ScraperService with minimal mocked config."""
        from scraper.service import ScraperService
        service = ScraperService.__new__(ScraperService)
        service._cfg = {
            "scraper": {"headless": True, "max_workers": 1, "slow_mo": 0, "page_load_timeout": 10},
            "queries": [
                {
                    "query": "ML Engineer",
                    "locations": ["Bangalore, India"],
                    "limit": 5,
                    "filters": {"relevance": "RECENT", "time": "MONTH", "type": ["FULL_TIME"]},
                }
            ],
        }
        service._scraper_cfg = service._cfg["scraper"]
        service._query_cfgs = service._cfg["queries"]
        service._lock = threading.Lock()
        service._collected = []
        service._stats = {"new": 0, "updated": 0, "errors": 0}
        service._run_id = None
        service.on_progress = None
        return service

    def test_build_queries_returns_correct_count(self, monkeypatch):
        service = self._make_service(monkeypatch)
        queries = service._build_queries()
        assert len(queries) == 1
        assert queries[0].query == "ML Engineer"

    def test_build_queries_multi_query(self, monkeypatch):
        service = self._make_service(monkeypatch)
        service._query_cfgs = [
            {"query": "MLE", "locations": ["Bangalore"], "limit": 10,
             "filters": {"relevance": "RECENT", "time": "MONTH", "type": ["FULL_TIME"]}},
            {"query": "Data Scientist", "locations": ["Mumbai"], "limit": 20,
             "filters": {"relevance": "RECENT", "time": "WEEK", "type": ["FULL_TIME", "CONTRACT"]}},
        ]
        queries = service._build_queries()
        assert len(queries) == 2
        assert queries[1].query == "Data Scientist"

    def test_on_data_collects_job(self, monkeypatch, in_memory_engine):
        """_on_data should append to _collected even when DB is mocked."""
        service = self._make_service(monkeypatch)
        # Mock out the DB upsert so test doesn't need a real DB
        monkeypatch.setattr(
            "scraper.service.SyncSession",
            MagicMock(return_value=MagicMock(
                __enter__=lambda s, *a: MagicMock(
                    **{"upsert_job.return_value": ("fake-id", True)}
                ),
                __exit__=MagicMock(return_value=False),
            )),
        )

        data = make_mock_event_data()
        service._on_data(data)

        assert len(service._collected) == 1
        captured = service._collected[0]
        assert captured["title"] == "Machine Learning Engineer"
        assert captured["description"] is not None
        assert captured["insights"] == ["Mid-Senior level", "Full-time", "Engineering", "Technology"]

    def test_on_data_captures_all_fields(self, monkeypatch):
        service = self._make_service(monkeypatch)
        monkeypatch.setattr("scraper.service.SyncSession", MagicMock(
            return_value=MagicMock(
                __enter__=lambda s, *a: MagicMock(
                    **{"upsert_job.return_value": ("id", True)}
                ),
                __exit__=MagicMock(return_value=False),
            )
        ))

        data = make_mock_event_data(
            apply_link="https://apply.me",
            company_link="https://linkedin.com/company/test",
            description_html="<p>Test</p>",
        )
        service._on_data(data)

        job = service._collected[0]
        assert job["apply_link"] == "https://apply.me"
        assert job["company_link"] == "https://linkedin.com/company/test"
        assert job["description_html"] == "<p>Test</p>"

    def test_on_error_increments_error_count(self, monkeypatch):
        service = self._make_service(monkeypatch)
        service._on_error(Exception("Test error"))
        assert service._stats["errors"] == 1

    def test_missing_cookie_raises(self, monkeypatch):
        from scraper.service import ScraperService
        service = self._make_service(monkeypatch)

        # Patch settings to return empty cookie
        monkeypatch.setattr("scraper.service.settings.li_at_cookie", "")

        with pytest.raises(ValueError, match="LI_AT_COOKIE"):
            service._set_cookie()

    def test_progress_callback_called(self, monkeypatch):
        service = self._make_service(monkeypatch)
        monkeypatch.setattr("scraper.service.SyncSession", MagicMock(
            return_value=MagicMock(
                __enter__=lambda s, *a: MagicMock(
                    **{"upsert_job.return_value": ("id", True)}
                ),
                __exit__=MagicMock(return_value=False),
            )
        ))

        calls = []
        service.on_progress = lambda job, stats: calls.append((job["title"], stats))

        service._on_data(make_mock_event_data())
        assert len(calls) == 1
        assert calls[0][0] == "Machine Learning Engineer"
        assert "new" in calls[0][1]
