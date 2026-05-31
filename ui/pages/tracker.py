"""
Application Tracker page — Kanban-style board.

Columns: Saved → Applied → Interview → Offer | Rejected

Features:
  - Shows all jobs by current status
  - One-click status transitions
  - Counts per column

Phase 5.
"""
from __future__ import annotations
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api


_COLUMNS = [
    ("saved",      "💾 Saved",     "#3b82f6"),
    ("applied",    "📬 Applied",   "#8b5cf6"),
    ("interview",  "🎤 Interview", "#f59e0b"),
    ("offer",      "🎉 Offer",     "#22c55e"),
    ("rejected",   "❌ Rejected",  "#ef4444"),
]

_TRANSITIONS = {
    "saved":     ["applied", "rejected"],
    "applied":   ["interview", "rejected"],
    "interview": ["offer", "rejected"],
    "offer":     [],
    "rejected":  ["saved"],
}


def _move_btn(job_id: str, label: str, new_status: str, key: str) -> None:
    if st.button(label, key=key, use_container_width=True):
        try:
            api.update_job_status(job_id, new_status)
            st.toast(f"Moved → {new_status}", icon="✅")
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))


def _mini_card(job: dict) -> None:
    """Compact card for the kanban column."""
    score = job.get("match_score")
    score_str = f"{score:.0%}" if score is not None else "—"

    st.html(
        f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;margin-bottom:8px;font-size:0.85rem;">'
        f'<div style="font-weight:700;">{job.get("title","—")}</div>'
        f'<div style="color:#94a3b8;">{job.get("company","—")}</div>'
        f'<div style="color:#6366f1;font-size:0.75rem;">Match: {score_str}</div>'
        f'</div>'
    )

    # Transition buttons
    current = job.get("status", "saved")
    nexts = _TRANSITIONS.get(current, [])
    if nexts:
        btn_cols = st.columns(len(nexts))
        for col, next_status in zip(btn_cols, nexts):
            label_map = {
                "applied": "📬", "interview": "🎤", "offer": "🎉",
                "rejected": "❌", "saved": "↩️",
            }
            with col:
                _move_btn(
                    job["id"],
                    f"{label_map.get(next_status,'')} {next_status.title()}",
                    next_status,
                    key=f"move_{job['id']}_{next_status}",
                )

    if job.get("apply_link") or job.get("link"):
        st.markdown(f"[🔗 View job]({job.get('apply_link') or job.get('link')})")

    st.divider()


def render() -> None:
    st.title("🗂️ Application Tracker")
    st.caption("Track every job you're pursuing — from saved to offer.")

    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # ── Load all tracked jobs ─────────────────────────────────────────────────
    all_tracked: dict[str, list[dict]] = {}
    for status, _, _ in _COLUMNS:
        try:
            jobs = api.list_jobs(status=status, limit=50, sort_by="scraped_at")
            all_tracked[status] = jobs
        except RuntimeError:
            all_tracked[status] = []

    # ── Summary row ───────────────────────────────────────────────────────────
    stat_cols = st.columns(len(_COLUMNS))
    for col, (status, label, colour) in zip(stat_cols, _COLUMNS):
        count = len(all_tracked.get(status, []))
        col.markdown(
            f"<div style='text-align:center;padding:8px;border-radius:8px;"
            f"background:{colour}22;border:1px solid {colour}44;'>"
            f"<div style='font-size:1.4rem;font-weight:700;color:{colour};'>{count}</div>"
            f"<div style='font-size:0.75rem;color:#64748b;'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Quick save from results ───────────────────────────────────────────────
    with st.expander("➕ Save a job to track", expanded=False):
        try:
            new_jobs = api.list_jobs(status="new", has_score=True, sort_by="match_score", limit=20)
            if new_jobs:
                for j in new_jobs[:10]:
                    score = j.get("match_score", 0)
                    lbl   = f"{j['title']} @ {j['company']} ({score:.0%})"
                    col1, col2 = st.columns([4, 1])
                    col1.write(lbl)
                    with col2:
                        if st.button("💾 Save", key=f"quick_save_{j['id']}"):
                            api.update_job_status(j["id"], "saved")
                            st.toast("Saved!", icon="💾")
                            st.rerun()
            else:
                st.caption("No new matched jobs to save. Run matching first.")
        except RuntimeError as e:
            st.caption(str(e))

    # ── Kanban columns ────────────────────────────────────────────────────────
    kanban_cols = st.columns(len(_COLUMNS))

    for col_widget, (status, label, colour) in zip(kanban_cols, _COLUMNS):
        with col_widget:
            st.markdown(
                f"<h4 style='color:{colour};border-bottom:2px solid {colour};padding-bottom:4px;'>"
                f"{label}</h4>",
                unsafe_allow_html=True,
            )
            jobs = all_tracked.get(status, [])
            if not jobs:
                st.caption("Empty")
            for job in jobs:
                _mini_card(job)
