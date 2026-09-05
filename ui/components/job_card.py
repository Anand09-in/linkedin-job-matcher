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


def _fmt_date(job: dict) -> str:
    """Return posting date if available, otherwise scraped_at formatted as a date string."""
    date_posted = job.get("date_posted")
    if date_posted:
        return date_posted
    scraped = job.get("scraped_at")
    if scraped:
        # scraped_at comes back as a datetime or ISO string from the API
        try:
            from datetime import datetime
            if isinstance(scraped, str):
                return datetime.fromisoformat(scraped).strftime("scraped %d %b")
            return scraped.strftime("scraped %d %b")
        except Exception:
            pass
    return "—"


def job_card(job: dict) -> str | None:
    score     = job.get("match_score")
    score_pct = f"{score:.0%}" if score is not None else "—"
    matched   = job.get("matched_skills") or []
    missing   = job.get("missing_skills") or []
    status    = job.get("status", "new")
    exp_years = job.get("experience_years")          # e.g. "3-5 years"
    exp_min   = job.get("experience_years_min")      # integer lower bound

    with st.container(border=True):
        # ── Header row ────────────────────────────────────────────────────────
        col_main, col_score = st.columns([5, 1])
        with col_main:
            st.markdown(f"**{job.get('title', '—')}**")
            st.caption(
                f"🏢 {job.get('company','—')}  |  "
                f"📍 {job.get('location') or 'N/A'}  |  "
                f"📅 {_fmt_date(job)}"
            )
            tags = [f"`{status.upper()}`"]
            if job.get("seniority_level"): tags.append(f"`{job['seniority_level']}`")
            if job.get("remote_policy"):   tags.append(f"`{job['remote_policy']}`")
            if job.get("employment_type"): tags.append(f"`{job['employment_type']}`")
            # Experience required — prefer the human-readable string, fall back to min years
            if exp_years:
                tags.append(f"`🕐 {exp_years}`")
            elif exp_min is not None:
                tags.append(f"`🕐 {exp_min}+ yrs`")
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
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 1])

        _STATUS_LABELS = {
            "saved":     "💾 Saved ✓",
            "applied":   "✅ Applied ✓",
            "interview": "🎤 Interview ✓",
            "offer":     "🎉 Offer ✓",
            "rejected":  "❌ Rejected ✓",
        }

        with col1:
            if job.get("apply_link") or job.get("link"):
                st.link_button("🔗 Apply", job.get("apply_link") or job.get("link", ""), use_container_width=True)
        with col2:
            is_saved = status == "saved"
            if st.button(
                _STATUS_LABELS["saved"] if is_saved else "💾 Save",
                key=f"save_{job['id']}",
                use_container_width=True,
                disabled=is_saved,
            ):
                action = "saved"
        with col3:
            is_applied = status in ("applied", "interview", "offer")
            if st.button(
                _STATUS_LABELS.get(status, "✅ Applied") if is_applied else "✅ Applied",
                key=f"applied_{job['id']}",
                use_container_width=True,
                disabled=is_applied,
            ):
                action = "applied"
        with col4:
            is_rejected = status == "rejected"
            if st.button(
                _STATUS_LABELS["rejected"] if is_rejected else "❌ Reject",
                key=f"reject_{job['id']}",
                use_container_width=True,
                disabled=is_rejected,
            ):
                action = "rejected"
        with col5:
            if st.button("🗑️", key=f"delete_{job['id']}", use_container_width=True, help="Remove this job"):
                action = "deleted"

    return action
