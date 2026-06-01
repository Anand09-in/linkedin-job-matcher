"""
✨ AI Features page — Phase 6 full implementation.

Layout:
  1. Career Path (standalone, top — no job selector needed)
  2. Job selector + 5 tabs: Cover Letter | ATS Score | Interview Prep | Company Research | Salary

All feature results are cached in st.session_state so re-renders don't re-spend LLM tokens.
Cache keys: "cp_result", "feat_{tab}_{job_id}"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import ui.api_client as api


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cache_key(tab: str, job_id: str) -> str:
    return f"feat_{tab}_{job_id}"


def _get_cached(tab: str, job_id: str):
    return st.session_state.get(_cache_key(tab, job_id))


def _set_cached(tab: str, job_id: str, data) -> None:
    st.session_state[_cache_key(tab, job_id)] = data


# ── Main render ───────────────────────────────────────────────────────────────

def render() -> None:
    import importlib, ui.api_client
    importlib.reload(ui.api_client)
    import ui.api_client as api  # noqa: F811 — intentional re-bind after reload

    st.title("✨ AI Features")
    st.caption("AI-powered career tools — results cached so you never pay twice for the same query.")

    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    resume_id: str | None = st.session_state.get("resume_id")

    # ── Sidebar: model override + cache management ────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("#### 🤖 AI Model Override")
        st.caption("Use a stronger model for this section without changing your .env")

        _PROVIDERS = ["Default (from .env)", "anthropic", "openai", "groq", "gemini", "ollama","bedrock"]
        provider_choice = st.selectbox(
            "Provider", _PROVIDERS,
            index=_PROVIDERS.index(st.session_state.get("feat_provider", "Default (from .env)")),
            key="feat_provider_select",
        )
        st.session_state["feat_provider"] = provider_choice

        model_choice = st.text_input(
            "Model name (blank = provider default)",
            value=st.session_state.get("feat_model", ""),
            placeholder="e.g. claude-opus-4-8",
            key="feat_model_input",
        )
        st.session_state["feat_model"] = model_choice

        # Quick-pick buttons — only providers you have credentials for
        st.caption("Quick picks (needs matching key in .env):")
        qcol1, qcol2 = st.columns(2)
        with qcol1:
            if st.button("Llama 70B\n(Groq)", key="qp_llama70", use_container_width=True):
                st.session_state["feat_provider"] = "groq"
                st.session_state["feat_model"] = "llama-3.3-70b-versatile"
                st.rerun()
            if st.button("Gemini 1.5 Pro\n(Google)", key="qp_gemini_pro", use_container_width=True):
                st.session_state["feat_provider"] = "gemini"
                st.session_state["feat_model"] = "gemini-1.5-pro"
                st.rerun()
        with qcol2:
            if st.button("DeepSeek 70B\n(Groq)", key="qp_deepseek", use_container_width=True):
                st.session_state["feat_provider"] = "groq"
                st.session_state["feat_model"] = "deepseek-r1-distill-llama-70b"
                st.rerun()
            if st.button("Claude Haiku\n(Bedrock)", key="qp_haiku_bedrock", use_container_width=True):
                st.session_state["feat_provider"] = "bedrock"
                st.session_state["feat_model"] = "anthropic.claude-3-haiku-20240307-v1:0"
                st.rerun()

        active_model = st.session_state.get("feat_model", "").strip()
        active_provider = st.session_state.get("feat_provider", "Default (from .env)")
        if active_model or active_provider != "Default (from .env)":
            st.success(f"Using: **{active_provider}** / `{active_model or 'default'}`")
            if st.button("↩ Reset to .env default", key="qp_reset", use_container_width=True):
                st.session_state["feat_provider"] = "Default (from .env)"
                st.session_state["feat_model"] = ""
                st.rerun()
        else:
            st.caption("ℹ️ Using default provider from `.env` (bedrock / meta.llama3-8b)")

        st.divider()
        st.markdown("#### 🗑️ Cache")
        st.caption("Cached results survive tab switches. Clear if you want fresh output.")
        if st.button("Clear all feature caches", key="clear_all_caches", use_container_width=True):
            keys_to_del = [k for k in st.session_state if k.startswith("feat_") or k == "cp_result"]
            for k in keys_to_del:
                del st.session_state[k]
            st.toast("All feature caches cleared", icon="🗑️")
            st.rerun()

    # Resolve model/provider to pass to API calls (None = use server default)
    _model    = st.session_state.get("feat_model", "").strip() or None
    _provider = st.session_state.get("feat_provider", "Default (from .env)")
    _provider = None if _provider == "Default (from .env)" else _provider

    # ── Section 1: Career Path (standalone) ───────────────────────────────────
    _render_career_path_section(resume_id, _model, _provider)

    st.divider()

    # ── Section 2: Job-level tools ────────────────────────────────────────────
    st.subheader("Per-Job Tools")

    try:
        jobs = api.list_jobs(has_score=True, sort_by="match_score", limit=50)
    except RuntimeError as e:
        st.error(str(e))
        return

    if not jobs:
        st.info("No matched jobs found. Run the matching pipeline on **Resume & Match** first.")
        return

    job_options = {
        f"{j['title']} @ {j['company']}  ({(j.get('match_score') or 0):.0%})": j
        for j in jobs
    }
    selected_label = st.selectbox("Choose a job to analyse", list(job_options.keys()))
    job = job_options[selected_label]
    job_id: str = job["id"]

    tab_cl, tab_ats, tab_ip, tab_ci, tab_ri = st.tabs([
        "✉️ Cover Letter",
        "📊 ATS Score",
        "🎤 Interview Prep",
        "🏢 Company & Salary",
        "📝 Resume Tips",
    ])

    with tab_cl:
        _cover_letter_tab(job_id, resume_id, _model, _provider)

    with tab_ats:
        _ats_tab(job_id, resume_id)

    with tab_ip:
        _interview_prep_tab(job_id, resume_id, _model, _provider)

    with tab_ci:
        _company_intel_tab(job_id, resume_id, _model, _provider)

    with tab_ri:
        _resume_improve_tab(job_id, resume_id, _model, _provider)


# ── Career Path section ───────────────────────────────────────────────────────

def _render_career_path_section(
    resume_id: str | None,
    model: str | None = None,
    provider: str | None = None,
) -> None:
    st.subheader("🗺️ Career Path Planner")
    st.caption("Uses your resume + all matched jobs to map where you can go now, in 6 months, and in 2 years.")

    cached = st.session_state.get("cp_result")

    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        generate = st.button("Generate Career Path", key="cp_generate", type="primary")
    with col_clear:
        if cached and st.button("Regenerate", key="cp_clear"):
            del st.session_state["cp_result"]
            st.rerun()

    if generate:
        with st.spinner("Analysing your career trajectory…"):
            try:
                data = api.generate_career_path(resume_id=resume_id, model=model, provider=provider)
                st.session_state["cp_result"] = data
                cached = data
            except RuntimeError as e:
                st.error(str(e))
                return

    if cached:
        st.caption("⚡ Loaded from session cache — click Regenerate for a fresh analysis")
        _render_career_path(cached)
    elif not generate:
        st.info("Click **Generate Career Path** to build your personalised roadmap.")


def _render_career_path(data: dict) -> None:
    st.markdown(f"**{data.get('current_title','')}** · {data.get('total_exp_years',0):.1f} years experience")
    st.info(data.get("summary", ""))

    horizons = data.get("horizons") or []
    if horizons:
        cols = st.columns(len(horizons))
        horizon_icons = {"now": "🟢", "6_months": "🟡", "2_years": "🔵"}
        for col, h in zip(cols, horizons):
            icon = horizon_icons.get(h.get("horizon", ""), "⚪")
            with col:
                st.markdown(f"#### {icon} {h.get('label','')}")
                roles = h.get("roles") or []
                if roles:
                    st.markdown("**Target Roles**")
                    for r in roles:
                        st.markdown(f"- {r}")
                actions = h.get("action_items") or []
                if actions:
                    st.markdown("**Actions**")
                    for a in actions:
                        st.markdown(f"- {a}")

    roadmap = data.get("learning_roadmap") or []
    if roadmap:
        st.divider()
        st.markdown("#### 📚 Learning Roadmap")
        for i, item in enumerate(roadmap, 1):
            with st.expander(
                f"{i}. **{item.get('skill','')}** — ~{item.get('estimated_weeks',0)} weeks",
                expanded=(i == 1),
            ):
                st.caption(f"**Unlocks:** {item.get('why','')}")
                resources = item.get("resources") or []
                if resources:
                    st.markdown("**Resources:**")
                    for r in resources:
                        st.markdown(f"- {r}")


# ── Cover Letter tab ──────────────────────────────────────────────────────────

def _cover_letter_tab(
    job_id: str, resume_id: str | None,
    model: str | None = None, provider: str | None = None,
) -> None:
    st.markdown("**AI Cover Letter Generator**")
    st.caption("Cliché-free 3-paragraph letter. Cached per job — switching tabs won't lose your letter.")
    tone = st.selectbox("Tone", ["professional", "confident", "friendly"], key=f"cl_tone_{job_id}")

    cache_tab = f"cl_{tone}"
    cached = _get_cached(cache_tab, job_id)
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run = st.button("Generate Cover Letter", key=f"cl_run_{job_id}")
    with col_clear:
        if cached and st.button("Regenerate", key=f"cl_clear_{job_id}"):
            _set_cached(cache_tab, job_id, None)
            st.rerun()

    if run:
        if cached:
            st.info("⚡ Using cached result — click **Regenerate** to get a fresh letter.")
        else:
            with st.spinner("Writing your cover letter…"):
                try:
                    data = api.generate_cover_letter(
                        job_id, tone=tone, resume_id=resume_id, model=model, provider=provider
                    )
                    _set_cached(cache_tab, job_id, data)
                    cached = data
                except RuntimeError as e:
                    st.error(str(e))
                    return

    if cached:
        server_cached = cached.get("cached", False)
        st.caption(
            f"⚡ Session cache  {'· also server-cached (LLM not re-called)' if server_cached else ''}"
            f"  ·  {cached.get('word_count', 0)} words  ·  {cached.get('tone','')} tone"
        )
        st.divider()
        st.markdown(cached.get("cover_letter", ""))
        st.download_button(
            "⬇️ Download as .txt",
            data=cached.get("cover_letter", ""),
            file_name=f"cover_letter_{cached.get('company','').replace(' ','_')}.txt",
            mime="text/plain",
            key=f"cl_dl_{job_id}",
        )


# ── ATS tab ───────────────────────────────────────────────────────────────────

def _ats_tab(job_id: str, resume_id: str | None) -> None:
    st.markdown("**ATS Keyword Scorer** · No LLM — runs instantly")
    st.caption("4 components: keyword density · title words · section headers · quantified achievements")

    cached = _get_cached("ats", job_id)
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run = st.button("Run ATS Analysis", key=f"ats_run_{job_id}")
    with col_clear:
        if cached and st.button("Refresh", key=f"ats_clear_{job_id}"):
            _set_cached("ats", job_id, None)
            st.rerun()

    if run:
        if cached:
            st.info("⚡ Using cached result — click **Refresh** to rescan.")
        else:
            with st.spinner("Scanning resume…"):
                try:
                    data = api.get_ats_score(job_id, resume_id=resume_id)
                    _set_cached("ats", job_id, data)
                    cached = data
                except RuntimeError as e:
                    st.error(str(e))
                    return

    if cached:
        _render_ats(cached)


def _render_ats(data: dict) -> None:
    score = data.get("overall_score", 0)
    pass_label = "✅ Likely to pass ATS" if data.get("predicted_pass") else "⚠️ May not pass ATS"

    c1, c2 = st.columns([2, 3])
    with c1:
        colour = "green" if score >= 70 else ("orange" if score >= 50 else "red")
        st.markdown(
            f"<div style='text-align:center;padding:16px;border-radius:10px;"
            f"border:2px solid {colour};'>"
            f"<div style='font-size:2.5rem;font-weight:700;color:{colour};'>{score:.0f}</div>"
            f"<div style='font-size:0.8rem;'>/100</div>"
            f"<div style='margin-top:4px;'>{pass_label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with c2:
        comps = data.get("components") or {}
        st.markdown("**Component breakdown**")
        comp_labels = {
            "keyword_density":         f"Keyword density  ({data.get('matched_keywords') and len(data['matched_keywords'])} matched)",
            "title_word_presence":     "Title word presence",
            "section_coverage":        "Standard sections",
            "quantified_achievements": f"Quantified achievements ({data.get('quant_count',0)} found)",
        }
        for key, label in comp_labels.items():
            val = comps.get(key, 0)
            st.progress(val, text=f"{label}: {val:.0%}")

    col_l, col_r = st.columns(2)
    with col_l:
        matched = data.get("matched_keywords") or []
        if matched:
            st.markdown("✅ **Matched Keywords**")
            st.markdown("  ".join(f"`{s}`" for s in matched))
    with col_r:
        missing = data.get("missing_keywords") or []
        if missing:
            st.markdown("❌ **Missing Keywords**")
            st.markdown("  ".join(f"`{s}`" for s in missing))

    tips = data.get("tips") or []
    if tips:
        st.divider()
        st.markdown("**Actionable Tips**")
        for t in tips:
            st.info(t)


# ── Interview Prep tab ────────────────────────────────────────────────────────

def _interview_prep_tab(
    job_id: str, resume_id: str | None,
    model: str | None = None, provider: str | None = None,
) -> None:
    st.markdown("**Interview Prep** · 12 questions across 4 categories")
    st.caption(
        "Technical · Behavioural · System Design · Culture Fit  "
        "— each with answer framework and key points. Cached per job."
    )

    cached = _get_cached("ip", job_id)
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run = st.button("Generate Questions", key=f"ip_run_{job_id}")
    with col_clear:
        if cached and st.button("Regenerate", key=f"ip_clear_{job_id}"):
            _set_cached("ip", job_id, None)
            st.rerun()

    if run:
        if cached:
            st.info("⚡ Using cached questions — click **Regenerate** for a fresh set.")
        else:
            with st.spinner("Generating 12 tailored questions…"):
                try:
                    data = api.generate_interview_prep(
                        job_id, resume_id=resume_id, model=model, provider=provider
                    )
                    _set_cached("ip", job_id, data)
                    cached = data
                except RuntimeError as e:
                    st.error(str(e))
                    return

    if cached:
        st.caption("⚡ Session cache active — switch tabs freely, questions won't disappear")

        tips = cached.get("prep_tips") or []
        if tips:
            with st.expander("📋 Prep Tips", expanded=True):
                for t in tips:
                    st.markdown(f"- {t}")

        cat_icons = {
            "technical": "⚙️", "behavioural": "🧠",
            "system_design": "🏗️", "culture_fit": "🤝",
        }
        cat_order = ["technical", "behavioural", "system_design", "culture_fit"]
        questions = cached.get("questions") or []

        by_cat: dict[str, list] = {}
        for q in questions:
            cat = q.get("category", "general").lower()
            by_cat.setdefault(cat, []).append(q)

        # Render in defined order, then any extras
        for cat in cat_order + [c for c in by_cat if c not in cat_order]:
            qs = by_cat.get(cat, [])
            if not qs:
                continue
            icon = cat_icons.get(cat, "❓")
            st.markdown(f"#### {icon} {cat.replace('_', ' ').title()}")
            for i, q in enumerate(qs, 1):
                fw = q.get("answer_framework", "") or ""
                label = f"{i}. {q.get('question','')}"
                with st.expander(label, expanded=False):
                    if fw:
                        st.caption(f"**Framework:** {fw}")
                    pts = q.get("key_points") or []
                    if pts:
                        st.markdown("**Key points to cover:**")
                        for pt in pts:
                            st.markdown(f"- {pt}")
                    elif not fw:
                        st.caption("No framework/key points returned — try Regenerate with a stronger model")


# ── Company & Salary (combined) tab ──────────────────────────────────────────

def _company_intel_tab(
    job_id: str, resume_id: str | None,
    model: str | None = None, provider: str | None = None,
) -> None:
    st.markdown("**Company Research + Salary Intelligence**")
    st.caption(
        "Searches the web for real salary data, mines LinkedIn signals, "
        "and runs one LLM call for both company analysis and salary interpretation."
    )

    cached = _get_cached("ci", job_id)
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run = st.button("Research Company & Salary", key=f"ci_run_{job_id}")
    with col_clear:
        if cached and st.button("Refresh", key=f"ci_clear_{job_id}"):
            _set_cached("ci", job_id, None)
            st.rerun()

    if run:
        if cached:
            st.info("⚡ Using cached result — click **Refresh** for a fresh analysis.")
        else:
            with st.spinner("Searching web for salary data + analysing company…"):
                try:
                    data = api.get_company_intel(
                        job_id, resume_id=resume_id, model=model, provider=provider
                    )
                    _set_cached("ci", job_id, data)
                    cached = data
                except RuntimeError as e:
                    st.error(str(e))
                    return

    if cached:
        st.caption("⚡ Session cache active — switch tabs freely")
        _render_company_intel(cached)


def _render_company_intel(data: dict) -> None:
    # ── Company metadata row ──────────────────────────────────────────────────
    meta_cols = st.columns(4)
    meta_cols[0].metric("Industry", data.get("industry") or "—")
    meta_cols[1].metric("Job Function", data.get("job_function") or "—")
    meta_cols[2].metric("Domain", data.get("domain") or "—")
    meta_cols[3].metric("Size", (data.get("size_hint") or "—").title())

    pills = []
    if data.get("remote_policy"):
        pills.append(f"🏠 `{data['remote_policy']}`")
    if data.get("employment_type"):
        pills.append(f"📋 `{data['employment_type']}`")
    if pills:
        st.markdown("  ".join(pills))

    # ── Overall impression ────────────────────────────────────────────────────
    st.markdown(f"**Overall Impression**  \n{data.get('overall_impression','')}")

    # ── Green / Red flags ─────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        for g in (data.get("green_flags") or []):
            st.success(f"🟢 {g}")
    with col_r:
        for r in (data.get("red_flags") or []):
            st.warning(f"🔴 {r}")

    # ── Culture + tech ────────────────────────────────────────────────────────
    signals = data.get("culture_signals") or []
    if signals:
        with st.expander("🧠 Culture Signals", expanded=False):
            for s in signals:
                st.markdown(f"- {s}")

    tech = data.get("tech_stack_hints") or []
    if tech:
        st.markdown("**Tech Stack**  " + "  ".join(f"`{t}`" for t in tech))

    st.divider()

    # ── Salary section ────────────────────────────────────────────────────────
    currency = data.get("salary_currency", "USD")
    source   = data.get("salary_source", "estimate")
    web_used = data.get("web_search_used", False)

    source_label = {
        "web":      "🌐 Web search",
        "jd":       "📄 Job description",
        "estimate": "📊 Market estimate",
    }.get(source, source)

    st.markdown(f"#### 💰 Salary Intelligence  <sub style='color:#64748b;'>{source_label}</sub>",
                unsafe_allow_html=True)

    search_query = data.get("search_query", "")
    snippets = data.get("search_snippets") or []

    if web_used and snippets:
        st.caption(f"Data from web search · query: `{search_query}`")
        with st.expander(f"🔍 View {len(snippets)} web sources", expanded=False):
            for i, s in enumerate(snippets, 1):
                title = s.get("title", "")
                body  = s.get("body", "")
                url   = s.get("url", "")
                st.markdown(f"**{i}. {title}**")
                st.markdown(body)
                if url:
                    st.markdown(f"[🔗 Source]({url})")
                if i < len(snippets):
                    st.divider()
    else:
        st.caption(
            "Web search unavailable — showing market estimates. "
            "Install for live data: `pip install ddgs`"
        )

    def _fmt(v):
        return f"{currency} {v:,.0f}" if v is not None else "—"

    sal_min = data.get("salary_min")
    sal_max = data.get("salary_max")

    if sal_min or sal_max:
        st.success(f"💰 **{source_label} range:** {_fmt(sal_min)} – {_fmt(sal_max)} / year")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Market Low",    _fmt(data.get("market_low", 0)))
    c2.metric("Market Median", _fmt(data.get("market_mid", 0)))
    c3.metric("Market High",   _fmt(data.get("market_high", 0)))
    c4.metric("Your Band",     (data.get("your_likely_band") or "—").replace("-", "‑"))

    tips = data.get("negotiation_tips") or []
    if tips:
        with st.expander("💬 Negotiation Tips", expanded=True):
            for t in tips:
                st.markdown(f"- {t}")

    benefits = data.get("benefits_to_ask") or []
    if benefits:
        with st.expander("📋 Benefits to Ask About"):
            for b in benefits:
                st.markdown(f"- {b}")


# ── Resume Tips tab ───────────────────────────────────────────────────────────

def _resume_improve_tab(
    job_id: str, resume_id: str | None,
    model: str | None = None, provider: str | None = None,
) -> None:
    st.markdown("**Resume Improvement Tips**")
    st.caption(
        "Section-by-section rewrites, missing keywords, a ready-to-paste summary, "
        "and the top 3 actions before you apply. Cached per job."
    )

    cached = _get_cached("ri", job_id)
    col_btn, col_clear = st.columns([3, 1])
    with col_btn:
        run = st.button("Analyse & Improve Resume", key=f"ri_run_{job_id}")
    with col_clear:
        if cached and st.button("Regenerate", key=f"ri_clear_{job_id}"):
            _set_cached("ri", job_id, None)
            st.rerun()

    if run:
        if cached:
            st.info("⚡ Using cached result — click **Regenerate** for a fresh analysis.")
        else:
            with st.spinner("Analysing your resume against this job description…"):
                try:
                    data = api.improve_resume(
                        job_id, resume_id=resume_id, model=model, provider=provider
                    )
                    _set_cached("ri", job_id, data)
                    cached = data
                except RuntimeError as e:
                    st.error(str(e))
                    return

    if cached:
        st.caption("⚡ Session cache active — switch tabs freely")
        _render_resume_improvement(cached)


def _render_resume_improvement(data: dict) -> None:
    # Detect incomplete output (LLM didn't return structured JSON)
    has_content = bool(
        data.get("top_actions")
        or data.get("keywords_to_add")
        or data.get("suggestions")
        or data.get("summary_rewrite")
    )
    if not has_content:
        st.error(
            "The model didn't return structured output — it's likely too small to follow "
            "the JSON schema reliably.\n\n"
            "**Fix:** use the sidebar model override to pick a stronger model:\n"
            "- **Llama 70B (Groq)** — free, already have the key\n"
            "- **Claude Haiku (Bedrock)** — best quality on your AWS account\n"
            "- **Gemini 1.5 Pro** — free tier available"
        )
        return

    grade = data.get("overall_fit_grade", "?")
    grade_colours = {"A": "#22c55e", "B": "#84cc16", "C": "#f59e0b", "D": "#ef4444"}
    colour = grade_colours.get(grade, "#94a3b8")

    # ── Header ────────────────────────────────────────────────────────────────
    col_grade, col_meta = st.columns([1, 4])
    with col_grade:
        st.markdown(
            f"<div style='text-align:center;padding:16px;border-radius:10px;"
            f"border:2px solid {colour};'>"
            f"<div style='font-size:2.8rem;font-weight:700;color:{colour};'>{grade}</div>"
            f"<div style='font-size:0.75rem;color:#94a3b8;'>Fit Grade</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with col_meta:
        st.markdown(f"**{data.get('job_title','')} @ {data.get('company','')}**")
        top_actions = data.get("top_actions") or []
        if top_actions:
            st.markdown("**🎯 Top Actions Before Applying**")
            for i, action in enumerate(top_actions, 1):
                st.markdown(f"{i}. {action}")

    # ── Keywords to add ───────────────────────────────────────────────────────
    keywords = data.get("keywords_to_add") or []
    if keywords:
        st.divider()
        st.markdown("**🔑 Keywords Missing from Your Resume**")
        st.caption("Add these exact terms to pass ATS scans for this role.")
        st.markdown("  ".join(f"`{k}`" for k in keywords))

    # ── Rewritten summary ─────────────────────────────────────────────────────
    rewrite = data.get("summary_rewrite", "")
    if rewrite:
        st.divider()
        with st.expander("✏️ Rewritten Professional Summary (ready to paste)", expanded=True):
            st.markdown(rewrite)
            st.download_button(
                "⬇️ Copy as .txt",
                data=rewrite,
                file_name=f"summary_{data.get('company','').replace(' ','_')}.txt",
                mime="text/plain",
                key=f"ri_dl_{data.get('job_id','')}",
            )

    # ── Section suggestions ───────────────────────────────────────────────────
    suggestions = data.get("suggestions") or []
    if suggestions:
        st.divider()
        st.markdown("**📋 Section-by-Section Improvements**")

        priority_order = {"high": 0, "medium": 1, "low": 2}
        sorted_suggestions = sorted(
            suggestions, key=lambda s: priority_order.get(s.get("priority", "low"), 2)
        )

        priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for s in sorted_suggestions:
            icon = priority_icons.get(s.get("priority", "low"), "⚪")
            section = s.get("section", "General")
            issue = s.get("issue", "")
            label = f"{icon} **{section}** — {issue}"
            with st.expander(label, expanded=(s.get("priority") == "high")):
                st.markdown(f"**What to do:** {s.get('suggestion','')}")
                example = s.get("example")
                if example:
                    st.markdown("**Example:**")
                    st.code(example, language=None)
