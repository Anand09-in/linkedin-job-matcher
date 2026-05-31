"""
Job Results dashboard page.

Features:
  - Filter sidebar (score, company, location, seniority, remote, status)
  - Stats row (total, avg score, top company)
  - Score distribution chart
  - Paginated job cards with action buttons
  - Job detail expander with score breakdown

Phase 5.
"""
from __future__ import annotations
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api
from ui.components.job_card import job_card
from ui.components.match_chart import score_breakdown_chart, score_distribution_chart


_PAGE_SIZE = 10


def _apply_status_update(job_id: str, new_status: str) -> None:
    try:
        api.update_job_status(job_id, new_status)
        st.toast(f"Status updated → {new_status}", icon="✅")
        # Bust the cached results so the card refreshes
        if "scored_jobs" in st.session_state:
            for j in st.session_state["scored_jobs"]:
                if j["id"] == job_id:
                    j["status"] = new_status
    except RuntimeError as e:
        st.error(str(e))


def render() -> None:
    st.title("📋 Job Results")

    # ── API check ─────────────────────────────────────────────────────────────
    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # ── Sidebar filters ───────────────────────────────────────────────────────
    with st.sidebar:
        st.header("🔧 Filters")

        min_score_pct = st.slider("Min match score", 0, 100, 0, 5, format="%d%%")
        min_score = min_score_pct / 100
        company   = st.text_input("Company", placeholder="e.g. Google")
        title_f   = st.text_input("Job title", placeholder="e.g. ML Engineer")
        location  = st.text_input("Location", placeholder="e.g. Bangalore")

        seniority = st.selectbox(
            "Seniority", ["All", "Entry", "Junior", "Mid", "Senior", "Lead", "Principal"]
        )
        remote = st.selectbox("Work mode", ["All", "Remote", "Hybrid", "On-site"])
        status = st.selectbox(
            "Application status",
            ["All", "new", "saved", "applied", "interview", "offer", "rejected"]
        )
        has_score = st.checkbox("Only matched jobs", value=True)

        sort_by = st.selectbox("Sort by", ["match_score", "scraped_at", "company", "title"])

        st.divider()
        page = st.number_input("Page", min_value=1, value=1, step=1)
        st.caption(f"Showing {_PAGE_SIZE} per page")

    # ── Fetch jobs ────────────────────────────────────────────────────────────
    try:
        jobs = api.list_jobs(
            min_score=min_score if min_score > 0 else None,
            company=company or None,
            title=title_f or None,
            location=location or None,
            status=status if status != "All" else None,
            seniority=seniority if seniority != "All" else None,
            remote_policy=remote if remote != "All" else None,
            has_score=True if has_score else None,
            sort_by=sort_by,
            limit=_PAGE_SIZE,
            offset=(_PAGE_SIZE * (page - 1)),
        )
    except RuntimeError as e:
        st.error(str(e))
        return

    # ── Stats row ─────────────────────────────────────────────────────────────
    try:
        stats = api.get_job_stats()
    except Exception:
        stats = {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total jobs",    stats.get("total_jobs", "—"))
    c2.metric("Matched",       stats.get("with_match_score", "—"))
    c3.metric("Avg score",     f"{stats.get('avg_match_score', 0):.0%}")
    c4.metric("Showing",       len(jobs))

    # ── Score distribution (from session state if available) ──────────────────
    all_jobs = st.session_state.get("scored_jobs", jobs)
    if all_jobs:
        with st.expander("📊 Score distribution", expanded=False):
            score_distribution_chart(all_jobs)

    st.divider()

    # ── No results state ──────────────────────────────────────────────────────
    if not jobs:
        st.info(
            "No jobs found. Try:\n"
            "1. Run a scrape on the **Search & Scrape** page\n"
            "2. Run matching on the **Resume & Matching** page\n"
            "3. Adjust the filters"
        )
        return

    # ── Job cards ─────────────────────────────────────────────────────────────
    for job in jobs:
        action = job_card(job)
        if action:
            _apply_status_update(job["id"], action)
