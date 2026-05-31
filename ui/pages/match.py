"""
Resume Upload & Match page.

Features:
  - PDF upload → extract text → parse with LLM
  - Active resume profile preview (skills, experience, work history)
  - Run matching pipeline button
  - Match progress indicator

Phase 5.
"""
from __future__ import annotations
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api


def _profile_card(profile: dict) -> None:
    """Render a structured resume profile."""
    col1, col2, col3 = st.columns(3)
    col1.metric("👤 Name",       profile.get("name") or "—")
    col2.metric("💼 Title",      profile.get("current_title") or "—")
    col3.metric("📅 Experience", f"{profile.get('total_experience_years') or '—'} yrs")

    st.markdown("---")

    # Skills grid
    skill_col, tool_col, lang_col = st.columns(3)
    with skill_col:
        st.markdown("**🧠 Skills**")
        for s in (profile.get("skills") or [])[:12]:
            st.markdown(f"• {s}")
    with tool_col:
        st.markdown("**🛠️ Tools & Frameworks**")
        for t in (profile.get("tools") or [])[:12]:
            st.markdown(f"• {t}")
    with lang_col:
        st.markdown("**💻 Languages**")
        for l in (profile.get("languages") or [])[:8]:
            st.markdown(f"• {l}")
        st.markdown("**🏆 Certifications**")
        for c in (profile.get("certifications") or [])[:4]:
            st.markdown(f"• {c}")

    # Work history
    work = profile.get("work_history") or []
    if work:
        st.markdown("---")
        st.markdown("**📋 Work History**")
        for w in work:
            dur = f"({w.get('duration_years')} yrs)" if w.get('duration_years') else ""
            st.markdown(f"**{w.get('title')}** @ {w.get('company')} {dur}")
            if w.get("description"):
                st.caption(w["description"])

    # Education
    edu = profile.get("education") or []
    if edu:
        st.markdown("---")
        st.markdown("**🎓 Education**")
        for e in edu:
            st.markdown(
                f"**{e.get('degree')}** in {e.get('field') or '—'} — "
                f"{e.get('institution')} ({e.get('year') or '—'})"
            )


def render() -> None:
    st.title("📄 Resume & Matching")

    # ── API check ─────────────────────────────────────────────────────────────
    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # ── Upload section ────────────────────────────────────────────────────────
    st.subheader("1️⃣  Upload Resume")

    uploaded = st.file_uploader("Upload your PDF resume", type=["pdf"])

    if uploaded:
        with st.spinner("Extracting text from PDF…"):
            try:
                result = api.upload_resume(uploaded.read(), uploaded.name)
                resume_id = result["resume_id"]
                st.session_state["resume_id"] = resume_id
                st.success(
                    f"✅ Uploaded **{uploaded.name}** — "
                    f"{result['characters_extracted']:,} characters extracted"
                )
                st.caption(f"Resume ID: `{resume_id}`")
                st.caption(f"Preview: _{result['preview'][:150]}…_")
            except RuntimeError as e:
                st.error(str(e))

    # ── Parse section ─────────────────────────────────────────────────────────
    st.subheader("2️⃣  Parse with AI")

    resume_id = st.session_state.get("resume_id")

    if not resume_id:
        # Try loading active resume
        active = api.get_active_resume()
        if active:
            resume_id = active["resume_id"]
            st.session_state["resume_id"] = resume_id
            st.info(f"Using active resume: **{active.get('filename')}** (ID: `{resume_id[:12]}…`)")
        else:
            st.warning("Upload a PDF resume above first.")

    if resume_id:
        from config.settings import get_settings
        settings = get_settings()
        st.caption(f"LLM provider: **{settings.llm_provider}** / **{settings.llm_model}**")

        col1, col2 = st.columns(2)
        with col1:
            parse_clicked = st.button(
                "🤖 Parse Resume with AI",
                type="primary",
                use_container_width=True,
                help="Extracts your skills, experience, and work history using your configured LLM."
            )
        with col2:
            refresh = st.button("🔄 Load Active Profile", use_container_width=True)

        if parse_clicked:
            with st.spinner("Parsing resume with AI (this takes ~10 seconds)…"):
                try:
                    result = api.parse_resume(resume_id)
                    st.session_state["candidate_profile"] = result["profile"]
                    st.success("✅ Resume parsed and cached!")
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))

        if refresh:
            active = api.get_active_resume()
            if active and active.get("profile"):
                st.session_state["candidate_profile"] = active["profile"]
                st.rerun()

    # ── Profile preview ───────────────────────────────────────────────────────
    profile = st.session_state.get("candidate_profile")
    if not profile and resume_id:
        try:
            active = api.get_active_resume()
            if active and active.get("profile"):
                profile = active["profile"]
                st.session_state["candidate_profile"] = profile
        except Exception:
            pass

    if profile:
        st.divider()
        st.subheader("👤 Your Profile")
        _profile_card(profile)

    # ── Match section ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader("3️⃣  Run Matching")

    try:
        stats = api.get_job_stats()
        total = stats.get("total_jobs", 0)
        scored = stats.get("with_match_score", 0)
        st.markdown(
            f"📊 **{total}** jobs in database &nbsp;|&nbsp; "
            f"**{stats.get('with_description', 0)}** with descriptions &nbsp;|&nbsp; "
            f"**{scored}** already scored"
        )
    except RuntimeError:
        st.caption("Could not load job stats.")

    match_btn = st.button(
        "⚡ Run Full Matching Pipeline",
        type="primary",
        use_container_width=True,
        help=(
            "Parses all job descriptions (cached after first run), "
            "scores each against your resume, computes skill gaps."
        ),
    )

    if match_btn:
        if not resume_id:
            st.error("Upload and parse your resume first.")
        else:
            progress = st.progress(0, text="Starting pipeline…")
            with st.spinner("Running matching pipeline — this may take a few minutes for large job sets…"):
                try:
                    progress.progress(20, text="Scraper node: loading jobs from DB…")
                    result = api.run_match(resume_id=resume_id)
                    progress.progress(100, text="Done!")

                    scored_jobs = result.get("scored_jobs", [])
                    skill_gaps  = result.get("skill_gaps", [])
                    errors      = result.get("errors", [])

                    st.session_state["scored_jobs"] = scored_jobs
                    st.session_state["skill_gaps"]  = skill_gaps

                    top = scored_jobs[0] if scored_jobs else None

                    st.success(
                        f"✅ Matched **{len(scored_jobs)}** jobs. "
                        + (f"Top match: **{top['title']} @ {top['company']}** "
                           f"({top['match_score']:.0%})" if top else "")
                    )
                    if errors:
                        with st.expander(f"⚠️  {len(errors)} warnings"):
                            for e in errors:
                                st.caption(e)

                    st.info("→ Go to **Job Results** to see your ranked matches.")
                except RuntimeError as e:
                    progress.empty()
                    st.error(str(e))
