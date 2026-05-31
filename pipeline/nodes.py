"""
LangGraph node implementations.

Each function takes PipelineState, performs work, and returns a partial
state dict that LangGraph merges into the global state.

Graph topology (Phase 3):

    START
      │
    scraper_node          — fetch/load jobs from DB
      │
      ├─────────────────┐
      ▼                 ▼
    jd_parser_node    resume_parser_node    ← run in PARALLEL
      │                 │
      └────────┬────────┘
               ▼
           matcher_node          — score jobs, compute skill gaps
               │
              END

Phase 3.
"""
from __future__ import annotations

import concurrent.futures
from typing import Any

from loguru import logger
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.orm import sessionmaker

from config.llm_factory import get_llm
from config.settings import get_settings
from db.models import Job, Resume
from db.repository import SyncJobRepository, SyncSession
from parser.jd_parser import JDParser
from parser.resume_parser import ResumeParser
from pipeline.matcher import JobMatcher
from pipeline.state import PipelineState


# ─────────────────────────────────────────────────────────────────────────────
# Node 1: Scraper
# ─────────────────────────────────────────────────────────────────────────────

def scraper_node(state: PipelineState) -> dict:
    """
    Loads existing jobs from the DB (jobs with no match_score yet).

    Design decision: the scraper itself (Selenium/LinkedIn) is triggered
    separately via the FastAPI /scrape endpoint (it's blocking and long-running).
    This node loads already-scraped jobs from SQLite into the pipeline state
    so the rest of the graph can process them.

    If you want a fully self-contained run (scrape + parse + match in one call),
    set state["trigger_scrape"] = True — the node will run ScraperService first.
    """
    errors: list[str] = list(state.get("errors") or [])

    try:
        settings = get_settings()
        sync_url = settings.database_url.replace("+aiosqlite", "")
        engine = create_engine(sync_url, echo=False)
        Session = sessionmaker(bind=engine)

        resume_id = state.get("resume_id") or ""

        with Session() as session:
            # Only load jobs that need scoring:
            #   - never scored, OR scored with a different resume
            needs_scoring = session.execute(
                select(Job).where(
                    or_(
                        Job.match_score.is_(None),
                        Job.scored_with_resume_id.is_(None),
                        Job.scored_with_resume_id != resume_id,
                    )
                ).order_by(Job.scraped_at.desc())
            ).scalars().all()

            total = session.execute(select(func.count(Job.id))).scalar()
            raw_jobs = [j.to_dict() for j in needs_scoring]

        skipped = total - len(raw_jobs)
        logger.info(
            f"[scraper_node] {len(raw_jobs)} jobs need scoring, "
            f"{skipped} already scored with current resume — skipping"
        )
        return {"raw_jobs": raw_jobs, "errors": errors}

    except Exception as e:
        msg = f"scraper_node failed: {e}"
        logger.error(f"[scraper_node] {msg}")
        errors.append(msg)
        return {"raw_jobs": [], "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# Node 2: JD Parser
# ─────────────────────────────────────────────────────────────────────────────

def jd_parser_node(state: PipelineState) -> dict:
    """
    Enriches raw_jobs with structured fields extracted by JDParser.

    - Jobs that already have skills_required in DB are skipped (cached).
    - Remaining jobs are parsed concurrently (max 4 threads).
    - Parsed results are written back to the DB and added to state.

    Returns state["parsed_jobs"] — full list (enriched + already-parsed).
    """
    raw_jobs: list[dict] = state.get("raw_jobs") or []
    errors: list[str] = list(state.get("errors") or [])

    if not raw_jobs:
        logger.warning("[jd_parser_node] No jobs to parse")
        return {"parsed_jobs": [], "errors": errors}

    # Separate already-parsed jobs (skills_required present) from unparsed
    to_parse = [j for j in raw_jobs if not j.get("skills_required")]
    already_done = [j for j in raw_jobs if j.get("skills_required")]
    logger.info(
        f"[jd_parser_node] {len(to_parse)} to parse, "
        f"{len(already_done)} already enriched (cached)"
    )

    if not to_parse:
        return {"parsed_jobs": raw_jobs, "errors": errors}

    llm = get_llm()
    parser = JDParser(llm=llm)

    def parse_one(job: dict) -> dict:
        """Parse a single job's description and return enriched job dict."""
        description = job.get("description") or ""
        if not description.strip():
            logger.warning(f"[jd_parser_node] No description for job {job.get('id')}")
            return job

        parsed = parser.parse(description)
        enriched = {
            **job,
            "skills_required": parsed.skills_required,
            "skills_nice_to_have": parsed.skills_nice_to_have,
            "experience_years": parsed.experience_years,
            "experience_years_min": parsed.experience_years_min,
            "seniority_level": parsed.seniority_level,
            "employment_type": parsed.employment_type,
            "remote_policy": parsed.remote_policy,
            "education_required": parsed.education_required,
            "salary_range": parsed.salary_range,
        }

        # Persist parsed fields to DB
        try:
            with SyncSession() as session:
                repo = SyncJobRepository(session)
                repo.update_job_parsed_fields(job["id"], enriched)
        except Exception as e:
            logger.error(f"[jd_parser_node] DB write failed for {job.get('id')}: {e}")

        return enriched

    # Concurrent parsing — max 4 workers (respects LLM rate limits reasonably)
    parsed_new: list[dict] = []
    max_workers = min(4, len(to_parse))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(parse_one, job): job for job in to_parse}
        for future in concurrent.futures.as_completed(futures):
            try:
                parsed_new.append(future.result())
            except Exception as e:
                original_job = futures[future]
                msg = f"JD parse failed for job {original_job.get('id')}: {e}"
                logger.error(f"[jd_parser_node] {msg}")
                errors.append(msg)
                parsed_new.append(original_job)   # keep original on failure

    all_parsed = already_done + parsed_new
    logger.info(f"[jd_parser_node] Done — {len(all_parsed)} total parsed jobs")
    return {"parsed_jobs": all_parsed, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# Node 3: Resume Parser
# ─────────────────────────────────────────────────────────────────────────────

def resume_parser_node(state: PipelineState) -> dict:
    """
    Loads the active resume from DB, parses it into a structured candidate profile.

    If the resume has already been parsed (parsed_profile present in DB),
    the cached version is used and the LLM is not called.

    Returns state["candidate_profile"] and state["resume_text"].
    """
    errors: list[str] = list(state.get("errors") or [])
    resume_id: str = state.get("resume_id", "")

    # ── Load resume from DB ───────────────────────────────────────────────────
    settings = get_settings()
    sync_url = settings.database_url.replace("+aiosqlite", "")
    engine = create_engine(sync_url, echo=False)
    Session = sessionmaker(bind=engine)

    try:
        with Session() as session:
            if resume_id:
                resume = session.execute(
                    select(Resume).where(Resume.id == resume_id)
                ).scalar_one_or_none()
            else:
                # Fall back to most recently uploaded active resume
                resume = session.execute(
                    select(Resume)
                    .where(Resume.is_active == True)
                    .order_by(Resume.uploaded_at.desc())
                ).scalar_one_or_none()

            if not resume:
                msg = "No resume found in DB — upload a PDF first"
                logger.error(f"[resume_parser_node] {msg}")
                errors.append(msg)
                return {"candidate_profile": {}, "resume_text": "", "errors": errors}

            raw_text = resume.raw_text
            cached_profile = resume.parsed_profile
            db_resume_id = resume.id

    except Exception as e:
        msg = f"resume_parser_node DB load failed: {e}"
        logger.error(f"[resume_parser_node] {msg}")
        errors.append(msg)
        return {"candidate_profile": {}, "resume_text": "", "errors": errors}

    # ── Use cached if available ───────────────────────────────────────────────
    if cached_profile:
        logger.info(f"[resume_parser_node] Using cached profile for resume {db_resume_id}")
        return {
            "candidate_profile": cached_profile,
            "resume_text": raw_text,
            "resume_id": db_resume_id,
            "errors": errors,
        }

    # ── Parse with LLM ────────────────────────────────────────────────────────
    logger.info(f"[resume_parser_node] Parsing resume {db_resume_id} with LLM…")
    try:
        llm = get_llm()
        parser = ResumeParser(llm=llm)
        parsed = parser.parse(raw_text)
        profile = parsed.model_dump()

        # Save parsed profile back to DB
        with Session() as session:
            resume_obj = session.get(Resume, db_resume_id)
            if resume_obj:
                resume_obj.parsed_profile = profile
                session.commit()
                logger.info(f"[resume_parser_node] Cached parsed profile for {db_resume_id}")

        return {
            "candidate_profile": profile,
            "resume_text": raw_text,
            "resume_id": db_resume_id,
            "errors": errors,
        }

    except Exception as e:
        msg = f"Resume LLM parse failed: {e}"
        logger.error(f"[resume_parser_node] {msg}")
        errors.append(msg)
        return {"candidate_profile": {}, "resume_text": raw_text, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# Node 4: Matcher
# ─────────────────────────────────────────────────────────────────────────────

def matcher_node(state: PipelineState) -> dict:
    """
    Scores each parsed job against the candidate profile.
    Writes match scores back to the DB.
    Computes aggregated skill gaps.

    Returns state["scored_jobs"] and state["skill_gaps"].
    """
    parsed_jobs: list[dict] = state.get("parsed_jobs") or []
    candidate_profile: dict = state.get("candidate_profile") or {}
    resume_text: str = state.get("resume_text") or ""
    resume_id: str = state.get("resume_id") or ""
    errors: list[str] = list(state.get("errors") or [])

    if not parsed_jobs:
        logger.warning("[matcher_node] No parsed jobs to score")
        return {"scored_jobs": [], "skill_gaps": [], "errors": errors}

    if not candidate_profile:
        msg = "matcher_node: candidate_profile is empty — resume may not have parsed correctly"
        logger.warning(f"[matcher_node] {msg}")
        errors.append(msg)
        return {"scored_jobs": parsed_jobs, "skill_gaps": [], "errors": errors}

    try:
        matcher = JobMatcher()
        scored_jobs, skill_gaps = matcher.score_all(
            parsed_jobs,
            candidate_profile,
            resume_raw_text=resume_text,
        )

        # Persist match scores to DB, tagging each job with the resume used
        with SyncSession() as session:
            repo = SyncJobRepository(session)
            repo.batch_update_match_scores(scored_jobs, resume_id=resume_id)

        logger.info(f"[matcher_node] Done — {len(scored_jobs)} jobs scored, {len(skill_gaps)} skill gaps")
        return {"scored_jobs": scored_jobs, "skill_gaps": skill_gaps, "errors": errors}

    except Exception as e:
        msg = f"matcher_node failed: {e}"
        logger.error(f"[matcher_node] {msg}")
        errors.append(msg)
        return {"scored_jobs": parsed_jobs, "skill_gaps": [], "errors": errors}
