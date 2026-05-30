"""Reusable Streamlit job card component — Phase 5."""
from __future__ import annotations
import streamlit as st

def job_card(job: dict) -> None:
    """Render a single job as a styled card with match score badge."""
    # TODO Phase 5: implement rich card with skills pills, score ring, quick-action buttons
    st.write(f"**{job.get('title')}** @ {job.get('company')}")
