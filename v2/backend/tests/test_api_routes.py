"""
Integration tests for the Phase 7 API surface (app/api/routes/) — exercised
through the real FastAPI app via ASGI transport (conftest's `api_client`
fixture), against real Postgres (`repo`/`db_session`). Not exhaustive of
every filter combination (those are covered at the Repository level already
— test_repository.py, test_scrape_service.py, etc.) — this file's job is to
prove the HTTP <-> Repository wiring itself: status codes, response models,
and the error-path -> HTTP-status translations each route is responsible for.
"""
from __future__ import annotations

import uuid

import pytest


def _make_pdf_bytes(text: str) -> bytes:
    """Builds a real, minimal, extractable one-page PDF on the fly (via
    pymupdf, already a project dependency) rather than committing a static
    binary fixture — keeps the test self-contained and its content visible."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    return doc.tobytes()


# ── Resumes ──────────────────────────────────────────────────────────────────

async def test_resume_upload_list_detail_update_delete(api_client):
    pdf_bytes = _make_pdf_bytes("Jane Doe\nData Engineer\n3 years experience with Python and Spark.")

    create_resp = await api_client.post(
        "/resumes", data={"name": "Jane's Resume"}, files={"file": ("resume.pdf", pdf_bytes, "application/pdf")}
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["name"] == "Jane's Resume"
    assert "Data Engineer" in created["raw_text"]
    resume_id = created["id"]

    list_resp = await api_client.get("/resumes")
    assert list_resp.status_code == 200
    assert any(r["id"] == resume_id for r in list_resp.json())
    assert "raw_text" not in list_resp.json()[0]  # list response omits raw_text by design

    detail_resp = await api_client.get(f"/resumes/{resume_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["raw_text"] == created["raw_text"]

    rename_resp = await api_client.put(f"/resumes/{resume_id}", data={"name": "Renamed Resume"})
    assert rename_resp.status_code == 200
    assert rename_resp.json()["name"] == "Renamed Resume"
    assert rename_resp.json()["raw_text"] == created["raw_text"]  # unchanged — only name was sent

    delete_resp = await api_client.delete(f"/resumes/{resume_id}")
    assert delete_resp.status_code == 204
    assert (await api_client.get(f"/resumes/{resume_id}")).status_code == 404


async def test_resume_upload_eagerly_parses_and_caches_profile(api_client):
    """Per explicit user request: parsing happens right after upload, not
    lazily on first pipeline run (scrape_service.py's _resolve_resume_profile
    still has that lazy path too, as a fallback — this only tests the eager
    one via the real route)."""
    from unittest.mock import AsyncMock, patch

    from app.llm_tasks.schemas import ResumeProfile

    pdf_bytes = _make_pdf_bytes("Jane Doe, Senior Data Engineer, 6 years experience.")
    fake_profile = ResumeProfile(summary="Senior data engineer.", skills=["SQL", "Spark"], current_title="Senior Data Engineer", total_experience_years=6.0)

    with patch("app.llm_tasks.resume_parser.parse_resume", AsyncMock(return_value=fake_profile)) as mock_parse:
        create_resp = await api_client.post(
            "/resumes", data={"name": "Jane"}, files={"file": ("resume.pdf", pdf_bytes, "application/pdf")}
        )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert mock_parse.await_count == 1
    assert created["parsed_profile"]["current_title"] == "Senior Data Engineer"
    assert created["parsed_profile"]["skills"] == ["SQL", "Spark"]

    # Replacing the file re-parses immediately too, not just clears the cache.
    new_pdf = _make_pdf_bytes("Jane Doe, Staff Data Engineer, 8 years experience.")
    updated_profile = ResumeProfile(summary="Staff data engineer.", skills=["SQL", "Airflow"], current_title="Staff Data Engineer", total_experience_years=8.0)
    with patch("app.llm_tasks.resume_parser.parse_resume", AsyncMock(return_value=updated_profile)) as mock_reparse:
        update_resp = await api_client.put(
            f"/resumes/{created['id']}", files={"file": ("resume2.pdf", new_pdf, "application/pdf")}
        )
    assert update_resp.status_code == 200
    assert mock_reparse.await_count == 1
    assert update_resp.json()["parsed_profile"]["current_title"] == "Staff Data Engineer"


async def test_resume_upload_succeeds_even_if_eager_parse_fails(api_client):
    """Best-effort: a parse failure at upload time (e.g. a transient Bedrock
    error) must not fail the upload itself — the resume is still useful with
    just its raw text, and falls through to the lazy parse-on-first-run path."""
    from unittest.mock import AsyncMock, patch

    pdf_bytes = _make_pdf_bytes("Some resume text.")
    with patch("app.llm_tasks.resume_parser.parse_resume", AsyncMock(side_effect=RuntimeError("simulated Bedrock failure"))):
        resp = await api_client.post(
            "/resumes", data={"name": "R"}, files={"file": ("r.pdf", pdf_bytes, "application/pdf")}
        )
    assert resp.status_code == 201
    assert resp.json()["parsed_profile"] is None


async def test_resume_upload_rejects_non_pdf(api_client):
    resp = await api_client.post(
        "/resumes", data={"name": "Bad"}, files={"file": ("resume.txt", b"not a pdf", "text/plain")}
    )
    assert resp.status_code == 400


async def test_resume_delete_blocked_by_enabled_pipeline(api_client):
    pdf_bytes = _make_pdf_bytes("Some resume text.")
    resume = (
        await api_client.post("/resumes", data={"name": "R"}, files={"file": ("r.pdf", pdf_bytes, "application/pdf")})
    ).json()

    pipeline_resp = await api_client.post(
        "/pipelines", json={"name": "P", "site": "linkedin", "query": "Engineer", "resume_id": resume["id"]}
    )
    assert pipeline_resp.status_code == 201

    delete_resp = await api_client.delete(f"/resumes/{resume['id']}")
    assert delete_resp.status_code == 409


async def test_get_nonexistent_resume_404(api_client):
    assert (await api_client.get(f"/resumes/{uuid.uuid4()}")).status_code == 404


# ── Pipelines ────────────────────────────────────────────────────────────────

async def test_pipeline_create_requires_a_real_resume_id(api_client):
    resp = await api_client.post(
        "/pipelines", json={"name": "P", "site": "linkedin", "query": "Engineer", "resume_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


async def test_pipeline_crud(api_client):
    create_resp = await api_client.post(
        "/pipelines", json={"name": "Extract Only", "site": "linkedin", "query": "Data Engineer", "locations": ["Remote"]}
    )
    assert create_resp.status_code == 201
    pipeline = create_resp.json()
    assert pipeline["resume_id"] is None
    pipeline_id = pipeline["id"]

    list_resp = await api_client.get("/pipelines")
    assert any(p["id"] == pipeline_id for p in list_resp.json())

    update_resp = await api_client.put(f"/pipelines/{pipeline_id}", json={"enabled": False, "batch_size": 10})
    assert update_resp.status_code == 200
    assert update_resp.json()["enabled"] is False
    assert update_resp.json()["batch_size"] == 10
    assert update_resp.json()["query"] == "Data Engineer"  # untouched fields survive a partial update

    rejected_resp = await api_client.get(f"/pipelines/{pipeline_id}/rejected-jobs")
    assert rejected_resp.status_code == 200
    assert rejected_resp.json() == []

    delete_resp = await api_client.delete(f"/pipelines/{pipeline_id}")
    assert delete_resp.status_code == 204
    assert (await api_client.get(f"/pipelines/{pipeline_id}")).status_code == 404


# ── Scrape ───────────────────────────────────────────────────────────────────

async def test_trigger_scrape_enqueues_and_lists_runs(api_client):
    pipeline = (
        await api_client.post("/pipelines", json={"name": "P", "site": "linkedin", "query": "Engineer"})
    ).json()

    trigger_resp = await api_client.post("/scrape", json={"pipeline_id": pipeline["id"], "limit": 5})
    assert trigger_resp.status_code == 202
    assert trigger_resp.json()["enqueued"] is True

    # Real bug this guards against: run_scrape_task must land on the
    # dedicated LinkedIn queue, never arq's default — see
    # config.py's linkedin_scrape_queue_name docstring for why (only the
    # native worker listens there; the Docker worker never can pick one up).
    from app.core.config import get_settings
    from app.main import app

    assert app.state.redis.enqueued_queue_names == [get_settings().linkedin_scrape_queue_name]

    runs_resp = await api_client.get("/scrape/runs", params={"pipeline_id": pipeline["id"]})
    assert runs_resp.status_code == 200  # no run rows yet (enqueue was faked, nothing executed) — empty is fine

    assert (await api_client.get(f"/scrape/{uuid.uuid4()}")).status_code == 404


async def test_trigger_scrape_unknown_pipeline_404(api_client):
    resp = await api_client.post("/scrape", json={"pipeline_id": str(uuid.uuid4())})
    assert resp.status_code == 404


# ── Jobs ─────────────────────────────────────────────────────────────────────

async def _seed_job(api_client, repo):
    pipeline = (await api_client.post("/pipelines", json={"name": "P", "site": "linkedin", "query": "Engineer"})).json()
    job, _ = await repo.upsert_job(
        {
            "title": "Data Engineer", "company": "Acme", "link": f"https://x/{uuid.uuid4()}",
            "pipeline_id": uuid.UUID(pipeline["id"]), "source_site": "linkedin",
        }
    )
    return job


async def test_job_detail_status_update_and_soft_delete(api_client, repo):
    job = await _seed_job(api_client, repo)

    detail_resp = await api_client.get(f"/jobs/{job.id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["title"] == "Data Engineer"

    status_resp = await api_client.patch(f"/jobs/{job.id}/status", json={"status": "applied"})
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "applied"

    delete_resp = await api_client.delete(f"/jobs/{job.id}")
    assert delete_resp.status_code == 204
    # Soft delete: the row still exists, just excluded from default listing.
    still_there = await api_client.get(f"/jobs/{job.id}")
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "deleted"


async def test_job_not_found_404(api_client):
    assert (await api_client.get(f"/jobs/{uuid.uuid4()}")).status_code == 404


async def test_job_stats_and_count_before(api_client, repo):
    await _seed_job(api_client, repo)

    stats_resp = await api_client.get("/jobs/stats")
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_jobs"] >= 1

    count_resp = await api_client.get("/jobs/count-before", params={"before_date": "2099-01-01"})
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] >= 1


# ── Settings ─────────────────────────────────────────────────────────────────

async def test_settings_llm_get_and_put(api_client):
    put_resp = await api_client.put(
        "/settings/llm", json={"provider": "bedrock", "model": "anthropic.claude-3-haiku-20240307-v1:0", "temperature": 0.2, "max_tokens": 1500}
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["model"] == "anthropic.claude-3-haiku-20240307-v1:0"

    get_resp = await api_client.get("/settings/llm")
    assert get_resp.status_code == 200
    assert get_resp.json()["model"] == "anthropic.claude-3-haiku-20240307-v1:0"


async def test_scraper_credential_lifecycle(api_client):
    get_before = await api_client.get("/settings/scraper-credentials/linkedin")
    assert get_before.status_code == 200
    assert get_before.json() == {
        "site": "linkedin", "configured": False, "masked_value": None, "updated_at": None,
    }

    put_resp = await api_client.put("/settings/scraper-credentials/linkedin", json={"value": "fake-li-at-cookie"})
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["configured"] is True
    assert body["masked_value"].endswith("okie")  # last 4 chars only, to recognize it without exposing it
    assert "value" not in body  # the full value is never echoed back — it's a session credential, not display data


# ── Features (service logic is covered thoroughly in test_feature_service.py —
#    this just proves the HTTP error-status translation) ─────────────────────

async def test_feature_unknown_feature_returns_404(api_client, repo):
    job = await _seed_job(api_client, repo)
    resp = await api_client.post(f"/features/not_a_real_feature/{job.id}", json={})
    assert resp.status_code == 404


async def test_feature_job_not_found_returns_404(api_client):
    resp = await api_client.post(f"/features/cover_letter/{uuid.uuid4()}", json={})
    assert resp.status_code == 404


# ── Export ───────────────────────────────────────────────────────────────────

async def test_export_csv_and_excel(api_client, repo):
    await _seed_job(api_client, repo)

    csv_resp = await api_client.get("/export/csv", params={"has_score": False})
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")

    excel_resp = await api_client.get("/export/excel", params={"has_score": False})
    assert excel_resp.status_code == 200
    assert "spreadsheetml" in excel_resp.headers["content-type"]
