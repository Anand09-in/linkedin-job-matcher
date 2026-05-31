"""
Visualisation components for match scores and skill gaps.

Phase 5.
"""
from __future__ import annotations
import streamlit as st


def score_breakdown_chart(job: dict) -> None:
    """
    Render a horizontal bar breakdown of a job's score components.
    """
    import plotly.graph_objects as go

    bd = job.get("score_breakdown") or {}
    if not bd:
        st.caption("Score breakdown not available.")
        return

    labels   = ["Semantic similarity", "Skills overlap", "Experience fit", "Title match"]
    values   = [
        bd.get("semantic", 0),
        bd.get("skills", 0),
        bd.get("experience", 0),
        bd.get("title", 0),
    ]
    weights  = [0.40, 0.35, 0.15, 0.10]
    weighted = [round(v * w, 3) for v, w in zip(values, weights)]
    colours  = ["#6366f1", "#22c55e", "#f59e0b", "#0891b2"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=labels,
        x=values,
        orientation="h",
        marker_color=colours,
        text=[f"{v:.0%}" for v in values],
        textposition="outside",
        name="Raw score",
    ))
    fig.update_layout(
        title=dict(text="Score breakdown", font_size=14),
        xaxis=dict(range=[0, 1.15], tickformat=".0%", showgrid=False),
        yaxis=dict(autorange="reversed"),
        height=220,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def skill_gap_chart(gaps: list[dict], top_n: int = 15) -> None:
    """
    Horizontal bar chart of skill gaps sorted by frequency.
    """
    import plotly.graph_objects as go

    if not gaps:
        st.info("No skill gaps computed yet. Run matching first.")
        return

    top = gaps[:top_n]
    skills = [g["skill"] for g in top]
    freqs  = [g["frequency"] for g in top]
    pcts   = [g["pct_jobs"] for g in top]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=skills,
        x=pcts,
        orientation="h",
        marker_color="#ef4444",
        text=[f"{p:.0%} ({f} jobs)" for p, f in zip(pcts, freqs)],
        textposition="outside",
    ))
    fig.update_layout(
        title=dict(text="Skills you're missing most often", font_size=14),
        xaxis=dict(range=[0, 1.2], tickformat=".0%", showgrid=False, title="% of jobs requiring this skill"),
        yaxis=dict(autorange="reversed"),
        height=max(300, top_n * 28),
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


def score_distribution_chart(jobs: list[dict]) -> None:
    """
    Histogram of match scores across all jobs.
    """
    import plotly.graph_objects as go

    scores = [j["match_score"] for j in jobs if j.get("match_score") is not None]
    if not scores:
        st.caption("No match scores yet.")
        return

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=scores,
        nbinsx=20,
        marker_color="#6366f1",
        opacity=0.8,
    ))
    fig.update_layout(
        title=dict(text="Match score distribution", font_size=14),
        xaxis=dict(title="Match score", tickformat=".0%"),
        yaxis=dict(title="Number of jobs"),
        height=250,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


def skills_venn(matched: list[str], missing: list[str]) -> None:
    """Simple matched vs missing skill summary metrics."""
    total = len(matched) + len(missing)
    if total == 0:
        return
    pct = len(matched) / total

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ Matched", len(matched), help="Required skills you have")
    col2.metric("❌ Missing", len(missing), help="Required skills you lack")
    col3.metric("Coverage", f"{pct:.0%}", help="Fraction of required skills covered")
