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


_PAGE_SIZE = 30


def _apply_status_update(job_id: str, new_status: str) -> None:
    try:
        if new_status == "deleted":
            api.delete_job(job_id)
            st.toast("Job removed from results", icon="🗑️")
            if st.session_state.get("scored_jobs"):
                st.session_state["scored_jobs"] = [
                    j for j in st.session_state["scored_jobs"] if j["id"] != job_id
                ]
        else:
            api.update_job_status(job_id, new_status)
            st.toast(f"Status updated → {new_status}", icon="✅")
            if st.session_state.get("scored_jobs"):
                for j in st.session_state["scored_jobs"]:
                    if j["id"] == job_id:
                        j["status"] = new_status
        st.rerun()
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

        exp_range = st.slider("Experience required (yrs)", 0, 15, (0, 15), 1)
        min_exp = exp_range[0] if exp_range[0] > 0 else None
        max_exp = exp_range[1] if exp_range[1] < 15 else None

        company   = st.text_input("Company", placeholder="e.g. Google")
        title_f   = st.text_input("Job title", placeholder="e.g. ML Engineer")
        location  = st.text_input("Location", placeholder="e.g. Bangalore")

        seniority = st.selectbox(
            "Seniority", ["All", "Entry", "Junior", "Mid", "Senior", "Lead", "Principal"]
        )
        remote = st.selectbox("Work mode", ["All", "Remote", "Hybrid", "On-site"])
        status = st.selectbox(
            "Application status",
            ["New only", "All", "saved", "applied", "interview", "offer", "rejected"],
        )
        has_score = st.checkbox("Only matched jobs", value=True)

        sort_by_list = st.multiselect(
            "Sort by (ordered)",
            ["match_score", "experience", "scraped_at", "company", "title"],
            default=["match_score"],
        )
        sort_by = ",".join(sort_by_list) if sort_by_list else "match_score"

        st.divider()
        page = st.number_input("Page", min_value=1, value=1, step=1)
        st.caption(f"Showing {_PAGE_SIZE} per page")

    # ── Fetch jobs ────────────────────────────────────────────────────────────
    try:
        jobs = api.list_jobs(
            min_score=min_score if min_score > 0 else None,
            min_experience=min_exp,
            max_experience=max_exp,
            company=company or None,
            title=title_f or None,
            location=location or None,
            status="new" if status == "New only" else (None if status == "All" else status),
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

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 3])
    c1.metric("Total jobs",    stats.get("total_jobs", "—"))
    c2.metric("Matched",       stats.get("with_match_score", "—"))
    c3.metric("Avg score",     f"{stats.get('avg_match_score', 0):.0%}")
    c4.metric("Showing",       len(jobs))
    with c5:
        st.markdown(" ")
        ec1, ec2 = st.columns(2)
        with ec1:
            st.link_button(
                "⬇️ CSV",
                f"http://localhost:8000/export/csv?has_score={str(has_score).lower()}&min_score={min_score if min_score > 0 else 0}",
                use_container_width=True,
            )
        with ec2:
            st.link_button(
                "📊 Excel",
                f"http://localhost:8000/export/excel?has_score={str(has_score).lower()}&min_score={min_score if min_score > 0 else 0}",
                use_container_width=True,
            )

    # ── Bulk delete by posted date ────────────────────────────────────────────
    with st.expander("🗑️ Flush old jobs (permanent)"):
        st.caption(
            "Permanently deletes jobs from the database whose **posted date** is "
            "on or before the date you pick. This cannot be undone — use it to "
            "clear out stale postings after a long gap between scraping runs."
        )
        dc1, dc2, dc3 = st.columns([2, 2, 2])
        cutoff = dc1.date_input("Delete jobs posted on/before", value=None, key="bulk_delete_cutoff")
        confirm = dc2.checkbox("I understand this is permanent", key="bulk_delete_confirm")
        if dc3.button(
            "Delete jobs",
            type="primary",
            disabled=not (cutoff and confirm),
            use_container_width=True,
        ):
            try:
                result = api.delete_jobs_before(cutoff.isoformat())
                st.toast(
                    f"Permanently deleted {result['deleted_count']} job(s) posted on/before {cutoff}",
                    icon="🗑️",
                )
                st.session_state.pop("scored_jobs", None)
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))

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
