"""
job_card — reusable Streamlit component for a single job.
Phase 5.
"""
from __future__ import annotations
import streamlit as st


def _score_label(score: float | None) -> str:
    if score is None:  return "Not scored"
    if score >= 0.75:  return "🟢 Strong match"
    if score >= 0.55:  return "🟡 Good match"
    if score >= 0.40:  return "🟠 Partial match"
    return "🔴 Weak match"


def job_card(job: dict) -> str | None:
    score     = job.get("match_score")
    score_pct = f"{score:.0%}" if score is not None else "—"
    matched   = job.get("matched_skills") or []
    missing   = job.get("missing_skills") or []
    status    = job.get("status", "new")

    with st.container(border=True):
        # ── Header row ────────────────────────────────────────────────────────
        col_main, col_score = st.columns([5, 1])
        with col_main:
            st.markdown(f"**{job.get('title', '—')}**")
            st.caption(
                f"🏢 {job.get('company','—')}  |  "
                f"📍 {job.get('location') or 'N/A'}  |  "
                f"📅 {job.get('date_posted') or 'N/A'}"
            )
            tags = [f"`{status.upper()}`"]
            if job.get("seniority_level"): tags.append(f"`{job['seniority_level']}`")
            if job.get("remote_policy"):   tags.append(f"`{job['remote_policy']}`")
            if job.get("employment_type"): tags.append(f"`{job['employment_type']}`")
            st.markdown("  ".join(tags))
        with col_score:
            st.metric("Match", score_pct)
            st.caption(_score_label(score))

        # ── Skills ────────────────────────────────────────────────────────────
        if matched:
            st.markdown("✅ **Matched:** " + "  ".join(f"`{s}`" for s in matched[:10]))
        if missing:
            st.markdown("❌ **Missing:** " + "  ".join(f"`{s}`" for s in missing[:10]))

        # ── Details expander ──────────────────────────────────────────────────
        with st.expander(f"🔍 Details — {job.get('title')} @ {job.get('company')}"):
            col_left, col_right = st.columns([3, 2])
            with col_left:
                if job.get("description"):
                    st.markdown("**Job Description**")
                    st.markdown(job["description"][:2000])
                if job.get("salary_range"):
                    st.info(f"💰 Salary: {job['salary_range']}")
                if job.get("skills_nice_to_have"):
                    st.markdown("**Nice to have:** " + ", ".join(job["skills_nice_to_have"]))
            with col_right:
                from ui.components.match_chart import score_breakdown_chart, skills_venn
                score_breakdown_chart(job)
                skills_venn(matched, missing)

        # ── Action buttons ────────────────────────────────────────────────────
        action = None
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if job.get("apply_link") or job.get("link"):
                st.link_button("🔗 Apply", job.get("apply_link") or job.get("link", ""), use_container_width=True)
        with col2:
            if st.button("💾 Save", key=f"save_{job['id']}", use_container_width=True):
                action = "saved"
        with col3:
            if st.button("✅ Applied", key=f"applied_{job['id']}", use_container_width=True):
                action = "applied"
        with col4:
            if st.button("❌ Reject", key=f"reject_{job['id']}", use_container_width=True):
                action = "rejected"

    return action
