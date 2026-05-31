"""
Skill Gap Analysis page.

Features:
  - Bar chart of missing skills ranked by frequency
  - Skills you already have vs. what the market wants
  - Quick tips per skill gap

Phase 5.
"""
from __future__ import annotations
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api
from ui.components.match_chart import skill_gap_chart


_RESOURCES: dict[str, str] = {
    "kubernetes":       "https://kubernetes.io/docs/tutorials/",
    "docker":           "https://docs.docker.com/get-started/",
    "mlops":            "https://ml-ops.org/",
    "mlflow":           "https://mlflow.org/docs/latest/tutorials-and-examples/",
    "aws sagemaker":    "https://docs.aws.amazon.com/sagemaker/",
    "pytorch":          "https://pytorch.org/tutorials/",
    "tensorflow":       "https://www.tensorflow.org/tutorials",
    "spark":            "https://spark.apache.org/docs/latest/",
    "kafka":            "https://kafka.apache.org/documentation/",
    "rust":             "https://doc.rust-lang.org/book/",
    "golang":           "https://go.dev/learn/",
    "react":            "https://react.dev/learn",
    "langchain":        "https://python.langchain.com/docs/get_started/",
    "langgraph":        "https://langchain-ai.github.io/langgraph/",
    "dbt":              "https://docs.getdbt.com/docs/introduction",
    "airflow":          "https://airflow.apache.org/docs/",
}


def render() -> None:
    st.title("📈 Skill Gap Analysis")
    st.caption("Skills the market demands that aren't on your resume.")

    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # ── Load gaps ─────────────────────────────────────────────────────────────
    # Prefer session state (from last match run) but also pull from API
    session_gaps = st.session_state.get("skill_gaps")
    limit = st.slider("Skills to display", 5, 30, 15)

    try:
        api_gaps = api.get_skill_gaps(limit=limit)
        gaps = api_gaps.get("skill_gaps", [])
        total_jobs = api_gaps.get("total_jobs_analysed", 0)
    except RuntimeError as e:
        st.error(str(e))
        return

    if not gaps:
        st.info(
            "No skill gaps computed yet.\n\n"
            "Run **Resume & Matching → Run Full Matching Pipeline** first."
        )
        return

    # ── Summary metrics ───────────────────────────────────────────────────────
    st.metric("Jobs analysed", total_jobs)

    # ── Chart ─────────────────────────────────────────────────────────────────
    skill_gap_chart(gaps, top_n=limit)

    # ── Ranked table with resources ───────────────────────────────────────────
    st.divider()
    st.subheader("📚 Skill Gaps & Learning Resources")

    for i, gap in enumerate(gaps, 1):
        skill   = gap["skill"]
        freq    = gap["frequency"]
        pct     = gap["pct_jobs"]
        bar_len = int(pct * 20)
        bar     = "█" * bar_len + "░" * (20 - bar_len)

        resource = _RESOURCES.get(skill.lower())
        link_text = f" — [Learn →]({resource})" if resource else ""

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(
                f"**{i}. {skill}**{link_text}  \n"
                f"`{bar}` {pct:.0%} of jobs &nbsp;({freq} jobs)"
            )
        with col2:
            priority = "🔴 High" if pct >= 0.6 else ("🟡 Medium" if pct >= 0.3 else "🟢 Low")
            st.markdown(f"<br>{priority}", unsafe_allow_html=True)

    # ── Your skills for comparison ────────────────────────────────────────────
    profile = st.session_state.get("candidate_profile")
    if profile:
        st.divider()
        st.subheader("✅ Your Current Skills")
        all_skills = list(set(
            (profile.get("skills") or []) +
            (profile.get("tools") or []) +
            (profile.get("languages") or [])
        ))
        st.markdown(", ".join(f"`{s}`" for s in sorted(all_skills)))
