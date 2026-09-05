"""
Search & Scrape page.

Features:
  - Query builder (keyword, locations, filters)
  - Trigger scrape via POST /scrape
  - Real-time progress bar polling /scrape/{run_id}
  - Past scrape run history

Phase 5.
"""
from __future__ import annotations
import time
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api


def render() -> None:
    st.title("🔍 Search & Scrape Jobs")
    st.caption("Configure your search and trigger a fresh LinkedIn scrape.")

    # ── API health check ──────────────────────────────────────────────────────
    try:
        api.health()
    except RuntimeError as e:
        st.error(f"⚠️  {e}")
        st.stop()

    # ── Scheduler status ──────────────────────────────────────────────────────
    try:
        sched = api.get_scheduler_status()
        _render_scheduler_status(sched)
    except RuntimeError:
        pass   # scheduler status is non-critical, fail silently

    # ── Query builder ─────────────────────────────────────────────────────────
    st.subheader("Search Configuration")

    with st.form("scrape_form"):
        col1, col2 = st.columns(2)
        with col1:
            keyword = st.text_input(
                "Job keyword",
                value="Machine Learning Engineer",
                placeholder="e.g. Data Scientist, MLOps Engineer",
            )
        with col2:
            limit = st.number_input("Max jobs to fetch", min_value=5, max_value=200, value=50, step=5)

        locations_raw = st.text_area(
            "Locations (one per line)",
            value="Bangalore, India\nMumbai, India\nPune, India",
            height=100,
        )

        st.markdown("**Filters**")
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            time_filter = st.selectbox("Posted", ["MONTH", "WEEK", "DAY", "ANY"])
        with fc2:
            type_filter = st.selectbox("Job type", ["FULL_TIME", "CONTRACT", "PART_TIME", "INTERNSHIP"])
        with fc3:
            exp_filter = st.multiselect("Experience", ["ENTRY_LEVEL", "ASSOCIATE", "MID_SENIOR", "DIRECTOR"], default=[])
        with fc4:
            remote_filter = st.multiselect("Work mode", ["REMOTE", "HYBRID", "ON_SITE"], default=[])

        use_config = st.checkbox("Use config.yaml instead (ignore form above)", value=False)
        submitted = st.form_submit_button("🚀 Start Scrape", type="primary", use_container_width=True)

    if submitted:
        query_overrides = None
        if not use_config:
            locations = [l.strip() for l in locations_raw.splitlines() if l.strip()]
            filters: dict = {"relevance": "RECENT", "time": time_filter, "type": [type_filter]}
            if exp_filter:    filters["experience"]         = exp_filter
            if remote_filter: filters["on_site_or_remote"]  = remote_filter
            query_overrides = [{
                "query": keyword,
                "locations": locations,
                "limit": int(limit),
                "filters": filters,
            }]

        try:
            result = api.trigger_scrape(query_overrides)
            run_id = result["run_id"]
            st.session_state["current_run_id"] = run_id
            st.success(f"✅ Scrape started — run ID: `{run_id}`")
        except RuntimeError as e:
            st.error(str(e))

    # ── Live progress bar ─────────────────────────────────────────────────────
    run_id = st.session_state.get("current_run_id")
    if run_id:
        st.divider()
        st.subheader("⏳ Scrape Progress")

        status_placeholder = st.empty()
        bar_placeholder    = st.empty()
        detail_placeholder = st.empty()

        poll_btn = st.button("🔄 Refresh status")

        if poll_btn or st.session_state.get("auto_poll"):
            with st.spinner("Checking…"):
                try:
                    status = api.get_scrape_status(run_id)
                    s = status["status"]
                    jobs_found = status["jobs_found"]

                    if s == "running":
                        bar_placeholder.progress(0.0, text=f"Scraping… {jobs_found} jobs found so far")
                        status_placeholder.info(f"🔄 Running — {jobs_found} jobs captured")
                        st.session_state["auto_poll"] = True
                    elif s == "completed":
                        bar_placeholder.progress(1.0, text="Complete!")
                        status_placeholder.success(f"✅ Done — {jobs_found} jobs scraped")
                        detail_placeholder.caption(
                            f"Finished at: {status.get('finished_at','—')}"
                        )
                        st.session_state["auto_poll"] = False
                    elif s == "failed":
                        bar_placeholder.empty()
                        status_placeholder.error(f"❌ Failed: {status.get('error','unknown error')}")
                        st.session_state["auto_poll"] = False

                    # Auto-refresh every 5s while running
                    if st.session_state.get("auto_poll"):
                        time.sleep(5)
                        st.rerun()

                except RuntimeError as e:
                    status_placeholder.error(str(e))

    # ── Past runs ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📋 Scrape History")

    try:
        runs = api.list_scrape_runs(limit=8)
        if not runs:
            st.caption("No scrape runs yet.")
        else:
            for r in runs:
                icon = {"completed": "✅", "running": "⏳", "failed": "❌"}.get(r["status"], "❓")
                col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
                col1.write(f"{icon} `{r['run_id'][:12]}…`")
                col2.write(r["status"])
                col3.write(f"{r['jobs_found']} jobs")
                col4.write(str(r.get("started_at",""))[:16])
    except RuntimeError as e:
        st.warning(str(e))


def _render_scheduler_status(s: dict) -> None:
    """Compact scheduler status panel shown above the query builder."""
    if not s.get("enabled"):
        return

    from datetime import datetime, timezone

    last  = s.get("last_run") or {}
    nxt   = s.get("next_run")
    hours = s.get("interval_hours", 12)
    now   = datetime.now(timezone.utc)

    # ── Format next run — absolute timestamp + relative in metric ────────────
    if nxt:
        try:
            dt = datetime.fromisoformat(nxt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta_mins = int((dt - now).total_seconds() / 60)
            if delta_mins <= 0:
                nxt_label = "soon"
            elif delta_mins < 60:
                nxt_label = f"in {delta_mins}m"
            else:
                h, m = divmod(delta_mins, 60)
                nxt_label = f"in {h}h {m}m"
            nxt_full = dt.strftime("%d %b %Y, %H:%M UTC")
        except Exception:
            nxt_label = nxt[:16]
            nxt_full  = nxt
    else:
        nxt_label = "—"
        nxt_full  = "Scheduler not running"

    # ── Format last run — relative time ("3h ago") + absolute in help ────────
    last_status  = last.get("status", "never")
    last_icon    = {"success": "✅", "failed": "❌", "running": "⏳"}.get(last_status, "—")
    last_ran_str = last.get("ran_at") or ""
    last_label   = "Never"
    last_full    = "No runs recorded yet"

    if last_ran_str:
        try:
            last_dt = datetime.fromisoformat(last_ran_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            ago_mins = int((now - last_dt).total_seconds() / 60)
            if ago_mins < 1:
                last_label = "just now"
            elif ago_mins < 60:
                last_label = f"{ago_mins}m ago"
            elif ago_mins < 1440:
                last_label = f"{ago_mins // 60}h ago"
            else:
                last_label = f"{ago_mins // 1440}d ago"
            last_full = last_dt.strftime("%d %b %Y, %H:%M UTC")
        except Exception:
            last_label = last_ran_str[:10]
            last_full  = last_ran_str

    with st.container(border=True):
        st.caption("🕐 Auto-Scrape Scheduler")
        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Next scrape",
            nxt_label,
            help=nxt_full,
        )
        c2.metric("Interval", f"Every {hours}h")
        c3.metric(
            "Last run",
            f"{last_icon} {last_label}" if last_ran_str else "—  Never",
            help=f"{last_full}  ·  status: {last_status}",
        )
        if last_status == "success":
            c4.metric(
                "Jobs found",
                f"+{last.get('jobs_new', 0)} new",
                delta=f"{last.get('jobs_updated', 0)} updated",
                delta_color="off",
            )
        elif last_status == "failed":
            c4.markdown(
                f"<span style='color:#ef4444;font-size:0.8rem;'>"
                f"⚠️ {(last.get('error') or 'unknown error')[:80]}</span>",
                unsafe_allow_html=True,
            )
        elif last_status == "running":
            c4.markdown("⏳ Scrape in progress…")
        else:
            c4.metric("Jobs found", "—")
