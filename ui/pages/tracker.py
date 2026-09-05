"""
Application Tracker — Kanban board + Referral Pipeline (Option A).

Every Kanban card shows a referral badge and a 🤝 popover for quick-add.
The Referral tab is a people-CRM that cross-references the live job status.
"""
from __future__ import annotations
import json
import streamlit as st
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import ui.api_client as api

# ── Referral storage ──────────────────────────────────────────────────────────

_REFERRAL_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "referrals.json"


def _load_referrals() -> dict:
    try:
        _REFERRAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _REFERRAL_FILE.exists():
            return json.loads(_REFERRAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_referrals(data: dict) -> None:
    try:
        _REFERRAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        _REFERRAL_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        st.error(f"Could not save referral data: {e}")


# ── Constants ─────────────────────────────────────────────────────────────────

_COLUMNS = [
    ("saved",     "💾 Saved",     "#3b82f6"),
    ("applied",   "📬 Applied",   "#8b5cf6"),
    ("interview", "🎤 Interview", "#f59e0b"),
    ("offer",     "🎉 Offer",     "#22c55e"),
    ("rejected",  "❌ Rejected",  "#ef4444"),
]

_TRANSITIONS = {
    "saved":     ["applied", "rejected"],
    "applied":   ["interview", "rejected"],
    "interview": ["offer", "rejected"],
    "offer":     [],
    "rejected":  ["saved"],
}

_REFERRAL_STATUSES = ["Not asked", "Asked", "Responded", "Referred", "Declined"]
_REF_ICON = {
    "Not asked": "⬜", "Asked": "📨", "Responded": "💬",
    "Referred": "✅",  "Declined": "❌",
}
_REF_COLOUR = {
    "Not asked": "#94a3b8", "Asked": "#3b82f6", "Responded": "#f59e0b",
    "Referred": "#22c55e",  "Declined": "#ef4444",
}
# Higher = better for sorting
_REF_RANK = {s: i for i, s in enumerate(["Declined", "Not asked", "Asked", "Responded", "Referred"])}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _best_referral(job_id: str, referrals: dict) -> dict | None:
    """Return the highest-ranked referral for a job, or None."""
    matches = [r for r in referrals.values() if r.get("job_id") == job_id]
    if not matches:
        return None
    return max(matches, key=lambda r: _REF_RANK.get(r.get("status", "Not asked"), 0))


def _ref_count(job_id: str, referrals: dict) -> int:
    return sum(1 for r in referrals.values() if r.get("job_id") == job_id)


def _move_btn(job_id: str, label: str, new_status: str, key: str) -> None:
    if st.button(label, key=key, use_container_width=True):
        try:
            api.update_job_status(job_id, new_status)
            st.toast(f"Moved → {new_status}", icon="✅")
            st.rerun()
        except RuntimeError as e:
            st.error(str(e))


# ── Kanban mini-card with referral popover ────────────────────────────────────

def _mini_card(job: dict, referrals: dict) -> None:
    score    = job.get("match_score")
    score_str = f"{score:.0%}" if score is not None else "—"
    jid      = job["id"]
    current  = job.get("status", "saved")

    best_ref = _best_referral(jid, referrals)
    count    = _ref_count(jid, referrals)

    with st.container(border=True):
        # ── Job title + score ─────────────────────────────────────────────
        st.markdown(f"**{job.get('title', '—')}**")
        st.caption(f"{job.get('company', '—')}  ·  Match: {score_str}")

        # ── Referral badge + popover ──────────────────────────────────────
        if best_ref:
            status_val = best_ref.get("status", "Not asked")
            icon       = _REF_ICON[status_val]
            colour     = _REF_COLOUR[status_val]
            badge_label = f"{icon} {status_val}" + (f" ×{count}" if count > 1 else "")
            st.markdown(
                f"<span style='background:{colour}22;border:1px solid {colour}66;"
                f"border-radius:12px;padding:2px 8px;font-size:0.75rem;color:{colour};'>"
                f"{badge_label}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<span style='background:#f1f5f9;border:1px solid #cbd5e1;"
                "border-radius:12px;padding:2px 8px;font-size:0.75rem;color:#94a3b8;'>"
                "⬜ No referral</span>",
                unsafe_allow_html=True,
            )

        # ── 🤝 Ask referral popover ───────────────────────────────────────
        pop_label = "🤝 Add contact" if not best_ref else "🤝 Add another"
        with st.popover(pop_label, use_container_width=True):
            st.markdown(f"**Referral for:** {job.get('title')} @ {job.get('company')}")
            p_name   = st.text_input("Contact name *", key=f"pop_name_{jid}", placeholder="e.g. Rahul Sharma")
            p_role   = st.text_input("Their role", key=f"pop_role_{jid}", placeholder="e.g. Senior Engineer")
            p_knows  = st.text_input("How you know them", key=f"pop_knows_{jid}", placeholder="e.g. College friend")
            p_status = st.selectbox("Status", _REFERRAL_STATUSES, key=f"pop_status_{jid}")
            p_notes  = st.text_area("Notes / message draft", key=f"pop_notes_{jid}", height=68,
                                    placeholder="LinkedIn URL, draft message, reminder...")
            p_applied = st.checkbox("I also applied directly", key=f"pop_applied_{jid}")

            if st.button("Save", key=f"pop_save_{jid}", type="primary", use_container_width=True):
                name_val = st.session_state.get(f"pop_name_{jid}", "").strip()
                if name_val:
                    refs = _load_referrals()
                    ref_id = f"{jid}_{name_val.lower().replace(' ', '_')}_{int(datetime.utcnow().timestamp())}"
                    refs[ref_id] = {
                        "job_id":       jid,
                        "job_title":    job.get("title", ""),
                        "company":      job.get("company", ""),
                        "job_link":     job.get("apply_link") or job.get("link", ""),
                        "contact_name": name_val,
                        "contact_role": st.session_state.get(f"pop_role_{jid}", ""),
                        "how_you_know": st.session_state.get(f"pop_knows_{jid}", ""),
                        "status":       st.session_state.get(f"pop_status_{jid}", "Not asked"),
                        "also_applied": st.session_state.get(f"pop_applied_{jid}", False),
                        "notes":        st.session_state.get(f"pop_notes_{jid}", ""),
                        "created_at":   datetime.utcnow().isoformat(),
                        "updated_at":   datetime.utcnow().isoformat(),
                    }
                    _save_referrals(refs)
                    st.toast(f"Referral contact added: {name_val}", icon="🤝")
                    st.rerun()
                else:
                    st.warning("Contact name is required.")

        # ── Transition buttons ────────────────────────────────────────────
        nexts = _TRANSITIONS.get(current, [])
        if nexts:
            label_map = {
                "applied": "📬", "interview": "🎤", "offer": "🎉",
                "rejected": "❌", "saved": "↩️",
            }
            btn_cols = st.columns(len(nexts))
            for col, next_status in zip(btn_cols, nexts):
                with col:
                    _move_btn(
                        jid,
                        f"{label_map.get(next_status, '')} {next_status.title()}",
                        next_status,
                        key=f"move_{jid}_{next_status}",
                    )

        if job.get("apply_link") or job.get("link"):
            st.markdown(
                f"<a href='{job.get('apply_link') or job.get('link')}' "
                f"target='_blank' style='font-size:0.78rem;'>🔗 View job</a>",
                unsafe_allow_html=True,
            )


# ── Kanban board ──────────────────────────────────────────────────────────────

def _render_kanban(referrals: dict) -> None:
    all_tracked: dict[str, list[dict]] = {}
    for status, _, _ in _COLUMNS:
        try:
            all_tracked[status] = api.list_jobs(status=status, limit=50, sort_by="scraped_at")
        except RuntimeError:
            all_tracked[status] = []

    # Summary counters
    stat_cols = st.columns(len(_COLUMNS))
    for col, (status, label, colour) in zip(stat_cols, _COLUMNS):
        count = len(all_tracked.get(status, []))
        col.markdown(
            f"<div style='text-align:center;padding:8px;border-radius:8px;"
            f"background:{colour}22;border:1px solid {colour}44;'>"
            f"<div style='font-size:1.4rem;font-weight:700;color:{colour};'>{count}</div>"
            f"<div style='font-size:0.75rem;color:#64748b;'>{label}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # Quick-save expander
    with st.expander("➕ Save a job to track", expanded=False):
        try:
            new_jobs = api.list_jobs(status="new", has_score=True, sort_by="match_score", limit=20)
            if new_jobs:
                for j in new_jobs[:10]:
                    score = j.get("match_score", 0)
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"{j['title']} @ {j['company']} ({score:.0%})")
                    with c2:
                        if st.button("💾", key=f"quick_save_{j['id']}"):
                            api.update_job_status(j["id"], "saved")
                            st.toast("Saved!", icon="💾")
                            st.rerun()
            else:
                st.caption("No new matched jobs. Run matching first.")
        except RuntimeError as e:
            st.caption(str(e))

    # Kanban columns
    kanban_cols = st.columns(len(_COLUMNS))
    for col_widget, (status, label, colour) in zip(kanban_cols, _COLUMNS):
        with col_widget:
            st.markdown(
                f"<h4 style='color:{colour};border-bottom:2px solid {colour};"
                f"padding-bottom:4px;margin-bottom:12px;'>{label}</h4>",
                unsafe_allow_html=True,
            )
            jobs = all_tracked.get(status, [])
            if not jobs:
                st.caption("Empty")
            for job in jobs:
                _mini_card(job, referrals)


# ── Referral CRM tab ──────────────────────────────────────────────────────────

def _render_referrals(referrals: dict, job_status_lookup: dict) -> None:
    st.subheader("🤝 Referral Pipeline")
    st.caption("Everyone you've asked (or plan to ask) for a referral.")

    # ── Full add form ─────────────────────────────────────────────────────────
    with st.expander("➕ Add referral request manually", expanded=not referrals):
        try:
            candidates = api.list_jobs(has_score=True, sort_by="match_score", limit=100)
            job_opts = {
                f"{j['title']} @ {j['company']}": j
                for j in candidates
                if j.get("status") not in ("rejected", "deleted")
            }
        except RuntimeError:
            job_opts = {}

        if not job_opts:
            st.caption("No jobs found. Scrape and match jobs first.")
        else:
            sel_label = st.selectbox("Job", list(job_opts.keys()), key="ref_full_job")
            sel_job   = job_opts.get(sel_label)
            ca, cb = st.columns(2)
            with ca:
                f_name  = st.text_input("Contact name *", key="ref_full_name", placeholder="Rahul Sharma")
                f_role  = st.text_input("Their role", key="ref_full_role", placeholder="Senior DE @ Google")
            with cb:
                f_knows  = st.text_input("How you know them", key="ref_full_knows", placeholder="College friend")
                f_status = st.selectbox("Status", _REFERRAL_STATUSES, key="ref_full_status")
            f_notes   = st.text_area("Notes / message draft", key="ref_full_notes", height=72)
            f_applied = st.checkbox("I also applied directly", key="ref_full_applied")

            if st.button("Add referral", type="primary", key="ref_full_add"):
                name_val = st.session_state.get("ref_full_name", "").strip()
                if sel_job and name_val:
                    ref_id = f"{sel_job['id']}_{name_val.lower().replace(' ', '_')}_{int(datetime.utcnow().timestamp())}"
                    referrals[ref_id] = {
                        "job_id":       sel_job["id"],
                        "job_title":    sel_job.get("title", ""),
                        "company":      sel_job.get("company", ""),
                        "job_link":     sel_job.get("apply_link") or sel_job.get("link", ""),
                        "contact_name": name_val,
                        "contact_role": st.session_state.get("ref_full_role", ""),
                        "how_you_know": st.session_state.get("ref_full_knows", ""),
                        "status":       st.session_state.get("ref_full_status", "Not asked"),
                        "also_applied": st.session_state.get("ref_full_applied", False),
                        "notes":        st.session_state.get("ref_full_notes", ""),
                        "created_at":   datetime.utcnow().isoformat(),
                        "updated_at":   datetime.utcnow().isoformat(),
                    }
                    _save_referrals(referrals)
                    st.toast(f"Added: {name_val}", icon="🤝")
                    st.rerun()
                else:
                    st.warning("Select a job and enter a contact name.")

    if not referrals:
        st.info("No referrals yet. Use the 🤝 button on any Kanban card to add one quickly.")
        return

    # ── Stats ─────────────────────────────────────────────────────────────────
    counts = {s: 0 for s in _REFERRAL_STATUSES}
    for r in referrals.values():
        counts[r.get("status", "Not asked")] += 1

    sc = st.columns(len(_REFERRAL_STATUSES))
    for col, status in zip(sc, _REFERRAL_STATUSES):
        c = _REF_COLOUR[status]
        col.markdown(
            f"<div style='text-align:center;padding:6px;border-radius:8px;"
            f"background:{c}22;border:1px solid {c}44;'>"
            f"<div style='font-size:1.2rem;font-weight:700;color:{c};'>{counts[status]}</div>"
            f"<div style='font-size:0.72rem;color:#64748b;'>{_REF_ICON[status]} {status}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Referral cards ────────────────────────────────────────────────────────
    # Group by job for cleaner reading
    by_job: dict[str, list[tuple[str, dict]]] = {}
    for ref_id, ref in referrals.items():
        jid = ref.get("job_id", "unknown")
        by_job.setdefault(jid, []).append((ref_id, ref))

    for jid, ref_list in by_job.items():
        job_app_status = job_status_lookup.get(jid)
        job_title = ref_list[0][1].get("job_title", "Unknown")
        company   = ref_list[0][1].get("company", "")

        # Job header with live application status
        app_colour = {
            "saved": "#3b82f6", "applied": "#8b5cf6", "interview": "#f59e0b",
            "offer": "#22c55e", "rejected": "#ef4444",
        }.get(job_app_status or "", "#94a3b8")
        app_badge = ""
        if job_app_status:
            app_badge = (
                f"<span style='background:{app_colour}22;border:1px solid {app_colour}66;"
                f"border-radius:10px;padding:1px 8px;font-size:0.72rem;color:{app_colour};"
                f"margin-left:8px;'>{job_app_status.title()}</span>"
            )

        st.markdown(
            f"<div style='font-weight:700;font-size:0.95rem;margin-bottom:4px;'>"
            f"📋 {job_title} @ {company}{app_badge}</div>",
            unsafe_allow_html=True,
        )

        for ref_id, ref in ref_list:
            ref_status = ref.get("status", "Not asked")
            icon   = _REF_ICON[ref_status]
            colour = _REF_COLOUR[ref_status]

            with st.container(border=True):
                h_col, s_col = st.columns([5, 1])
                with h_col:
                    st.markdown(
                        f"**{ref.get('contact_name')}**"
                        + (f" — {ref.get('contact_role')}" if ref.get("contact_role") else "")
                    )
                    if ref.get("how_you_know"):
                        st.caption(f"🤝 {ref['how_you_know']}")
                    if ref.get("also_applied"):
                        st.caption("✅ Also applied directly")
                    if ref.get("notes"):
                        st.markdown(
                            f"<div style='font-size:0.82rem;color:#64748b;"
                            f"border-left:3px solid #e2e8f0;padding-left:8px;"
                            f"margin-top:4px;'>{ref['notes'][:250]}</div>",
                            unsafe_allow_html=True,
                        )
                with s_col:
                    st.markdown(
                        f"<div style='text-align:center;padding:6px;border-radius:8px;"
                        f"background:{colour}22;border:1px solid {colour}44;'>"
                        f"<div style='font-size:1.3rem;'>{icon}</div>"
                        f"<div style='font-size:0.68rem;color:{colour};'>{ref_status}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                # Action row
                ac1, ac2, ac3, ac4 = st.columns([2, 2, 2, 1])
                with ac1:
                    new_status = st.selectbox(
                        "Status",
                        _REFERRAL_STATUSES,
                        index=_REFERRAL_STATUSES.index(ref_status),
                        key=f"ref_status_{ref_id}",
                        label_visibility="collapsed",
                    )
                    if new_status != ref_status:
                        referrals[ref_id]["status"] = new_status
                        referrals[ref_id]["updated_at"] = datetime.utcnow().isoformat()
                        _save_referrals(referrals)
                        st.rerun()
                with ac2:
                    if ref.get("job_link"):
                        st.link_button("🔗 Job", ref["job_link"], use_container_width=True)
                with ac3:
                    updated = ref.get("updated_at", ref.get("created_at", ""))[:10]
                    st.caption(f"Updated {updated}" if updated else "")
                with ac4:
                    if st.button("🗑️", key=f"ref_del_{ref_id}", help="Remove"):
                        del referrals[ref_id]
                        _save_referrals(referrals)
                        st.rerun()

        st.markdown("")  # spacing between job groups


# ── Page entry point ──────────────────────────────────────────────────────────

def render() -> None:
    st.title("🗂️ Application Tracker")
    st.caption("Kanban board + referral pipeline — two tracks, one view.")

    try:
        api.health()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()

    # Load shared state once — both tabs use the same referrals dict
    referrals = _load_referrals()

    # Build job_id → application_status lookup for the Referral tab
    try:
        all_jobs = api.list_jobs(limit=200, sort_by="scraped_at")
        job_status_lookup = {j["id"]: j.get("status") for j in all_jobs}
    except RuntimeError:
        job_status_lookup = {}

    tab_kanban, tab_referral = st.tabs(["📋 Kanban Board", "🤝 Referral Pipeline"])

    with tab_kanban:
        _render_kanban(referrals)

    with tab_referral:
        _render_referrals(referrals, job_status_lookup)
