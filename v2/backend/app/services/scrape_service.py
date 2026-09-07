"""
The core single-step pipeline: scrape -> extract+match (one LLM call per
batch) -> deterministic filter -> save. This is the redesign's central claim
(plan.md Phase 3, FR-2.5): there is no separate post-hoc "matching pipeline"
run. A job is fully processed — extracted, scored, filtered — before it is
ever persisted as a Job row.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from app.core.config import get_settings
from app.core.llm import get_llm
from app.domain.models import Pipeline, Resume
from app.domain.repository import Repository
from app.llm_tasks.batch_extract import analyze_batch
from app.llm_tasks.resume_parser import parse_resume
from app.llm_tasks.schemas import JobAnalysisResult, ResumeProfile
from app.scrapers.base import RawJob, ScrapeConfig
from app.scrapers.registry import get_scraper

settings = get_settings()


def _passes_filter(
    result: JobAnalysisResult, has_resume: bool, min_score: float, max_experience: Optional[int]
) -> bool:
    """
    Deterministic threshold check (system-design.md §3.3): the LLM scores,
    the system decides pass/fail. FR-2.6: a pipeline with no resume bound
    runs extract-only — every job passes, nothing is filtered.
    """
    if not has_resume:
        return True
    if result.match_score is None or result.match_score < min_score:
        return False
    if (
        max_experience is not None
        and result.experience_years_min is not None
        and result.experience_years_min > max_experience
    ):
        return False
    return True


def _rejection_reason(
    result: JobAnalysisResult, min_score: float, max_experience: Optional[int]
) -> str:
    if result.match_score is None or result.match_score < min_score:
        return "below_match_score_threshold"
    if (
        max_experience is not None
        and result.experience_years_min is not None
        and result.experience_years_min > max_experience
    ):
        return "exceeds_max_experience_years"
    return "unknown"  # shouldn't happen — _passes_filter said no, one of the above should match


async def _resolve_resume_profile(
    repo: Repository, resume: Optional[Resume], llm
) -> Optional[ResumeProfile]:
    """
    Resolve the compact profile used for every batch in this run — cached in
    Resume.parsed_profile so the (comparatively expensive, full-resume)
    parsing call happens ONCE per resume ever, not once per pipeline run and
    not once per batch.

    Raised directly by a real usage concern: LLM APIs are stateless per
    call, so the resume must physically be in every batch's request for the
    model to use it that call — that part can't be avoided. What this avoids
    is resending the FULL raw resume text every time; a ~150-300 token
    profile, computed once, gets reused instead.
    """
    if resume is None:
        return None
    if resume.parsed_profile:
        return ResumeProfile(**resume.parsed_profile)

    profile = await parse_resume(resume.raw_text, llm)
    await repo.update_resume_parsed_profile(resume.id, profile.model_dump())
    logger.info(f"[scrape_service] parsed and cached resume profile for resume={resume.id}")
    return profile


def _job_row(raw_job: RawJob, result: JobAnalysisResult, pipeline: Pipeline, run_id, resume_id) -> dict:
    return {
        "title": raw_job.title,
        "company": raw_job.company,
        "location": raw_job.location,
        "link": raw_job.link,
        "apply_link": raw_job.apply_link,
        "description": raw_job.description,
        "skills_required": result.skills_required,
        "skills_nice_to_have": result.skills_nice_to_have,
        "experience_years_min": result.experience_years_min,
        "seniority_level": result.seniority_level,
        "employment_type": result.employment_type,
        "remote_policy": result.remote_policy,
        "education_required": result.education_required,
        "match_score": result.match_score,
        "matched_skills": result.matched_skills,
        "missing_skills": result.missing_skills,
        "match_rationale": result.match_rationale,
        "scored_with_resume_id": resume_id,
        "pipeline_id": pipeline.id,
        "scrape_run_id": run_id,
        "source_site": pipeline.site,
        "date_posted": raw_job.date_posted,
    }


async def run_scrape_pipeline(repo: Repository, pipeline: Pipeline, limit: Optional[int] = None) -> dict:
    """
    Run one pipeline's scrape end to end. Returns a summary dict — the same
    shape a future GET /scrape/{run_id} (Phase 7) would report.

    Two distinct failure modes, handled differently (system-design.md §1.1):
      - A single batch's LLM call fails -> that batch's jobs are rejected,
        the run continues to the next batch.
      - The scraper adapter itself fails (can't reach the site at all) ->
        the whole run is marked failed.

    `limit` overrides ScrapeConfig's default job count — useful for manual
    test runs against real LinkedIn without pulling the full default every
    time (Phase 2 testing showed LinkedIn throttling after repeated
    rapid-fire full-size runs on one session).
    """
    resume = await repo.get_resume(pipeline.resume_id) if pipeline.resume_id else None

    min_score = (
        pipeline.min_match_score_override
        if pipeline.min_match_score_override is not None
        else settings.default_min_match_score
    )
    max_experience = (
        pipeline.max_experience_years_override
        if pipeline.max_experience_years_override is not None
        else settings.default_max_experience_years
    )

    run = await repo.create_scrape_run(
        pipeline.id,
        config_snapshot={
            "query": pipeline.query,
            "locations": pipeline.locations,
            "filters": pipeline.filters,
            "batch_size": pipeline.batch_size,
            "min_match_score": min_score,
            "max_experience_years": max_experience,
            "resume_id": str(resume.id) if resume else None,
        },
    )

    config_kwargs = dict(
        query=pipeline.query,
        locations=pipeline.locations,
        filters=pipeline.filters,
        batch_size=pipeline.batch_size,
    )
    if limit is not None:
        config_kwargs["limit"] = limit
    config = ScrapeConfig(**config_kwargs)
    scraper = get_scraper(pipeline.site)
    # A batch returns up to config.batch_size full structured results in one
    # response — needs more output headroom than the general-purpose default
    # (see llm_batch_extract_max_tokens's docstring for why this is separate).
    llm = get_llm(max_tokens=settings.llm_batch_extract_max_tokens)

    jobs_seen = jobs_saved = jobs_rejected = 0
    errors: list[str] = []

    async def _reject(raw_job: RawJob, reason: str, score: Optional[float] = None) -> None:
        nonlocal jobs_rejected
        await repo.create_rejected_job(
            scrape_run_id=run.id,
            pipeline_id=pipeline.id,
            title=raw_job.title,
            company=raw_job.company,
            link=raw_job.link,
            match_score=score,
            reason=reason,
        )
        jobs_rejected += 1

    try:
        # Parsed/cached ONCE per resume (not per run, not per batch) — see
        # _resolve_resume_profile's docstring. A failure here is treated the
        # same as an adapter-level failure (caught by this same try/except):
        # it's a run-setup prerequisite, not a per-batch concern.
        resume_profile = await _resolve_resume_profile(repo, resume, llm)
        has_resume = resume_profile is not None

        async for batch in scraper.scrape(config):
            jobs_seen += len(batch)

            try:
                analysis = await analyze_batch(batch, resume_profile, llm)
            except Exception as e:
                msg = f"batch of {len(batch)} failed LLM analysis: {e}"
                logger.error(f"[scrape_service] {msg}")
                errors.append(msg)
                for raw_job in batch:
                    await _reject(raw_job, "llm_batch_failed")
                await repo.update_scrape_run(
                    run.id, jobs_seen=jobs_seen, jobs_saved=jobs_saved, jobs_rejected=jobs_rejected
                )
                continue

            results_by_index = {r.job_index: r for r in analysis.results}
            for i, raw_job in enumerate(batch):
                result = results_by_index.get(i)
                if result is None:
                    await _reject(raw_job, "missing_from_llm_response")
                    continue

                if not _passes_filter(result, has_resume, min_score, max_experience):
                    await _reject(
                        raw_job,
                        _rejection_reason(result, min_score, max_experience),
                        score=result.match_score,
                    )
                    continue

                await repo.upsert_job(
                    _job_row(raw_job, result, pipeline, run.id, resume.id if resume else None)
                )
                jobs_saved += 1

            await repo.update_scrape_run(
                run.id, jobs_seen=jobs_seen, jobs_saved=jobs_saved, jobs_rejected=jobs_rejected
            )

    except Exception as e:
        # Covers both an adapter failure (can't reach the site) and a
        # resume-profile resolution failure (§ _resolve_resume_profile) —
        # both are run-setup prerequisites, not per-batch concerns.
        logger.error(f"[scrape_service] run failed: {e}")
        errors.append(str(e))
        await repo.update_scrape_run(
            run.id, jobs_seen=jobs_seen, jobs_saved=jobs_saved, jobs_rejected=jobs_rejected, errors=errors
        )
        await repo.finish_scrape_run(run.id, status="failed")
        return {
            "run_id": run.id, "status": "failed",
            "jobs_seen": jobs_seen, "jobs_saved": jobs_saved, "jobs_rejected": jobs_rejected,
            "errors": errors,
        }

    await repo.update_scrape_run(run.id, errors=errors)
    await repo.finish_scrape_run(run.id, status="completed")
    return {
        "run_id": run.id, "status": "completed",
        "jobs_seen": jobs_seen, "jobs_saved": jobs_saved, "jobs_rejected": jobs_rejected,
        "errors": errors,
    }
