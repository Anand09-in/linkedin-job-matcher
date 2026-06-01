"""
Streamlit app entry point.

Run with:
    streamlit run ui/app.py

Phase 5.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Remove broken SSL_CERT_FILE from conda env before httpx is imported anywhere
os.environ.pop("SSL_CERT_FILE", None)
os.environ.pop("REQUESTS_CA_BUNDLE", None)

# Make project root importable from ui/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(
    page_title="LinkedIn Job Matcher",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Tighten up default Streamlit padding */
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }
    /* Remove default button full width */
    .stButton > button { border-radius: 8px; }
    /* Metric card style */
    [data-testid="stMetric"] {
        border-radius: 10px;
        padding: 12px;
    }
    /* Hide auto-generated multi-page nav (we use our own radio) */
    [data-testid="stSidebarNav"] { display: none; }
    /* Hide Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ── Session state defaults ────────────────────────────────────────────────────
defaults = {
    "resume_id":         None,
    "candidate_profile": None,
    "scored_jobs":       None,
    "skill_gaps":        None,
    "current_run_id":    None,
    "auto_poll":         False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── Sidebar navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://cdn-icons-png.flaticon.com/512/174/174857.png",
        width=40,
    )
    st.title("Job Matcher")
    st.caption("AI-powered LinkedIn job search")
    st.divider()

    page = st.radio(
        "Navigate",
        [
            "🔍 Search & Scrape",
            "📄 Resume & Match",
            "📋 Job Results",
            "📈 Skill Gaps",
            "🗂️ Tracker",
            "✨ AI Features",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    # ── Quick status panel ────────────────────────────────────────────────────
    import ui.api_client as api

    try:
        stats = api.get_job_stats()
        st.caption(f"🗄️  **{stats.get('total_jobs',0)}** jobs in DB")
        st.caption(f"⚡ **{stats.get('with_match_score',0)}** matched")
        avg = stats.get("avg_match_score", 0)
        st.caption(f"📊 Avg score: **{avg:.0%}**")
    except Exception:
        st.caption("⚠️  API not connected")
        st.caption("Run: `uvicorn api.main:app --reload`")

    st.divider()

    # Show active resume in sidebar
    resume_id = st.session_state.get("resume_id")
    if resume_id:
        st.caption(f"📄 Resume loaded")
        st.caption(f"`{resume_id[:16]}…`")
    else:
        st.caption("📄 No resume uploaded")

# ── Reload all UI modules on every run so edits are picked up without restart ─
import importlib, sys
_UI_MODULES = [m for m in list(sys.modules) if m.startswith("ui.")]
for _mod in _UI_MODULES:
    try:
        importlib.reload(sys.modules[_mod])
    except Exception:
        pass

# ── Page routing ──────────────────────────────────────────────────────────────
if page == "🔍 Search & Scrape":
    from ui.pages import search
    search.render()

elif page == "📄 Resume & Match":
    from ui.pages import match
    match.render()

elif page == "📋 Job Results":
    from ui.pages import results
    results.render()

elif page == "📈 Skill Gaps":
    from ui.pages import skill_gaps
    skill_gaps.render()

elif page == "🗂️ Tracker":
    from ui.pages import tracker
    tracker.render()

elif page == "✨ AI Features":
    from ui.pages import features
    features.render()
