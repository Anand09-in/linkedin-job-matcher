"""
API client — wraps every FastAPI endpoint for use by Streamlit pages.

All methods return plain Python dicts/lists or raise RuntimeError with
a human-readable message. Pages never call httpx directly.

Phase 5.
"""
from __future__ import annotations

import os
from typing import Optional
import httpx
from loguru import logger

# Remove broken SSL_CERT_FILE set by conda env (file doesn't exist); safe since API is localhost HTTP
os.environ.pop("SSL_CERT_FILE", None)
os.environ.pop("REQUESTS_CA_BUNDLE", None)

BASE_URL = "http://localhost:8000"
TIMEOUT  = 300   # seconds — /match can be slow (LLM calls)

_CLIENT = httpx.Client(timeout=TIMEOUT, follow_redirects=True)


def _get(path: str, params: dict | None = None) -> dict | list:
    try:
        r = _CLIENT.get(f"{BASE_URL}{path}", params=params, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to API. Is `uvicorn api.main:app` running?")
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        raise RuntimeError(f"API error {e.response.status_code}: {detail}")


def _post(path: str, json: dict | None = None, files=None) -> dict:
    try:
        if files:
            r = _CLIENT.post(f"{BASE_URL}{path}", files=files, follow_redirects=True)
        else:
            r = _CLIENT.post(f"{BASE_URL}{path}", json=json or {}, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to API. Is `uvicorn api.main:app` running?")
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        raise RuntimeError(f"API error {e.response.status_code}: {detail}")


def _post_with_params(path: str, params: dict | None = None, json: dict | None = None) -> dict:
    try:
        r = _CLIENT.post(f"{BASE_URL}{path}", params=params, json=json or {}, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to API. Is `uvicorn api.main:app` running?")
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        raise RuntimeError(f"API error {e.response.status_code}: {detail}")


def _patch(path: str, json: dict) -> dict:
    try:
        r = _CLIENT.patch(f"{BASE_URL}{path}", json=json, follow_redirects=True)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        raise RuntimeError("Cannot connect to API.")
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = e.response.text or str(e)
        raise RuntimeError(f"API error {e.response.status_code}: {detail}")


# ── Health ────────────────────────────────────────────────────────────────────

def health() -> dict:
    return _get("/health")


# ── Scraper ───────────────────────────────────────────────────────────────────

def trigger_scrape(query_overrides: Optional[list[dict]] = None) -> dict:
    """POST /scrape — returns {run_id, status, jobs_found, ...}"""
    body = {}
    if query_overrides:
        body["queries"] = query_overrides
    return _post("/scrape", json=body)


def get_scrape_status(run_id: str) -> dict:
    """GET /scrape/{run_id}"""
    return _get(f"/scrape/{run_id}")


def list_scrape_runs(limit: int = 10) -> list:
    """GET /scrape/runs"""
    return _get("/scrape/runs", params={"limit": limit})


# ── Resume ────────────────────────────────────────────────────────────────────

def upload_resume(pdf_bytes: bytes, filename: str) -> dict:
    """POST /resume — returns {resume_id, filename, characters_extracted, ...}"""
    return _post("/resume", files={"file": (filename, pdf_bytes, "application/pdf")})


def parse_resume(resume_id: str) -> dict:
    """POST /resume/{id}/parse — returns {resume_id, profile}"""
    return _post(f"/resume/{resume_id}/parse")


def get_active_resume() -> dict | None:
    """GET /resume/active — returns resume info or None if not uploaded."""
    try:
        return _get("/resume/active")
    except RuntimeError as e:
        if "404" in str(e):
            return None
        raise


# ── Jobs ──────────────────────────────────────────────────────────────────────

def list_jobs(
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    company: Optional[str] = None,
    title: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[str] = None,
    seniority: Optional[str] = None,
    remote_policy: Optional[str] = None,
    has_description: Optional[bool] = None,
    has_score: Optional[bool] = None,
    sort_by: str = "match_score",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    params = {"sort_by": sort_by, "limit": limit, "offset": offset}
    if min_score  is not None: params["min_score"]      = min_score
    if max_score  is not None: params["max_score"]      = max_score
    if company:                params["company"]        = company
    if title:                  params["title"]          = title
    if location:               params["location"]       = location
    if status:                 params["status"]         = status
    if seniority:              params["seniority"]      = seniority
    if remote_policy:          params["remote_policy"]  = remote_policy
    if has_description is not None: params["has_description"] = has_description
    if has_score is not None:  params["has_score"]      = has_score
    return _get("/jobs", params=params)


def get_job(job_id: str) -> dict:
    return _get(f"/jobs/{job_id}")


def get_job_stats() -> dict:
    return _get("/jobs/stats")


def update_job_status(job_id: str, status: str) -> dict:
    """PATCH /jobs/{id}/status"""
    return _patch(f"/jobs/{job_id}/status", json={"status": status})


# ── Match ─────────────────────────────────────────────────────────────────────

def run_match(resume_id: Optional[str] = None) -> dict:
    """POST /match — runs full pipeline, returns {scored_jobs, skill_gaps, ...}"""
    body = {}
    if resume_id:
        body["resume_id"] = resume_id
    return _post("/match", json=body)


# ── Features ──────────────────────────────────────────────────────────────────

def get_skill_gaps(limit: int = 20) -> dict:
    """GET /features/skill-gaps"""
    return _get("/features/skill-gaps", params={"limit": limit})


def generate_cover_letter(
    job_id: str, tone: str = "professional",
    resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """POST /features/cover-letter/{job_id}"""
    params: dict = {"tone": tone}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _post_with_params(f"/features/cover-letter/{job_id}", params=params)


def get_ats_score(job_id: str, resume_id: str | None = None) -> dict:
    """GET /features/ats-score/{job_id}  (no LLM — no model param needed)"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    return _get(f"/features/ats-score/{job_id}", params=params or None)


def generate_interview_prep(
    job_id: str, resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """POST /features/interview-prep/{job_id}"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _post_with_params(f"/features/interview-prep/{job_id}", params=params)


def get_company_research(
    job_id: str, resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """GET /features/company-research/{job_id}"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _get(f"/features/company-research/{job_id}", params=params or None)


def get_salary_benchmark(job_id: str, resume_id: str | None = None) -> dict:
    """GET /features/salary-benchmark/{job_id}  (no LLM — no model param needed)"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    return _get(f"/features/salary-benchmark/{job_id}", params=params or None)


def get_tracker_stats() -> dict:
    """GET /features/tracker-stats"""
    return _get("/features/tracker-stats")


def get_company_intel(
    job_id: str, resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """GET /features/company-intel/{job_id} — combined company + salary with web search"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _get(f"/features/company-intel/{job_id}", params=params or None)


def improve_resume(
    job_id: str, resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """POST /features/resume-improve/{job_id}"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _post_with_params(f"/features/resume-improve/{job_id}", params=params)


def generate_career_path(
    resume_id: str | None = None,
    model: str | None = None, provider: str | None = None,
) -> dict:
    """POST /features/career-path — 3-horizon career plan + learning roadmap"""
    params: dict = {}
    if resume_id: params["resume_id"] = resume_id
    if model:     params["model"] = model
    if provider:  params["provider"] = provider
    return _post_with_params("/features/career-path", params=params)
