"""
Streamlit app entry point.

Run with:
    streamlit run ui/app.py
"""
import streamlit as st

st.set_page_config(
    page_title="LinkedIn Job Matcher",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sidebar navigation
st.sidebar.title("LinkedIn Job Matcher")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "Navigate",
    ["Search & Scrape", "Job Results", "Resume Match", "Skill Gaps", "Application Tracker"],
)

if page == "Search & Scrape":
    from ui.pages import search
    search.render()
elif page == "Job Results":
    from ui.pages import results
    results.render()
elif page == "Resume Match":
    from ui.pages import match
    match.render()
elif page == "Skill Gaps":
    from ui.pages import skill_gaps
    skill_gaps.render()
elif page == "Application Tracker":
    from ui.pages import tracker
    tracker.render()
