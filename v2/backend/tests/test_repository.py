"""
Phase 1 exit-criteria tests (plan.md):
  - repository test suite green against Postgres
  - DELETE-by-date / count-before ported and behaviorally identical to v1's,
    now backed by a real timestamptz column, composable with pipeline_id
  - two resumes + two pipelines (one per resume) coexist, jobs listed per
    pipeline_id work with no cross-contamination
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain.exceptions import ResumeInUseError


async def _make_resume(repo, name="AI Engineer resume"):
    return await repo.create_resume(name=name, filename=f"{name}.pdf", raw_text=f"resume text for {name}")


async def _make_pipeline(repo, resume, name="AI Engineer pipeline", **overrides):
    kwargs = dict(
        name=name,
        site="linkedin",
        query="AI Engineer",
        locations=["Bangalore, India"],
        filters={"time": "WEEK"},
        resume_id=resume.id if resume else None,
    )
    kwargs.update(overrides)
    return await repo.create_pipeline(**kwargs)


def _job_data(pipeline, resume=None, **overrides) -> dict:
    data = dict(
        title="ML Engineer",
        company="Acme Corp",
        location="Bangalore, India",
        link=f"https://linkedin.com/jobs/{overrides.get('_uid', 'x')}",
        description="Build ML models.",
        pipeline_id=pipeline.id,
        source_site=pipeline.site,
        scored_with_resume_id=resume.id if resume else None,
        match_score=0.75,
    )
    data.update({k: v for k, v in overrides.items() if k != "_uid"})
    return data


# ── Resume + Pipeline coexistence (FR-1A) ───────────────────────────────────


async def test_multiple_resumes_and_pipelines_coexist(repo):
    ai_resume = await _make_resume(repo, "AI Engineer resume")
    de_resume = await _make_resume(repo, "Data Engineer resume")

    ai_pipeline = await _make_pipeline(repo, ai_resume, name="AI Engineer pipeline", query="AI Engineer")
    de_pipeline = await _make_pipeline(repo, de_resume, name="Data Engineer pipeline", query="Data Engineer")

    resumes = await repo.list_resumes()
    assert {r.name for r in resumes} == {"AI Engineer resume", "Data Engineer resume"}

    pipelines = await repo.list_pipelines()
    assert {p.name for p in pipelines} == {"AI Engineer pipeline", "Data Engineer pipeline"}
    assert ai_pipeline.resume_id == ai_resume.id
    assert de_pipeline.resume_id == de_resume.id
    assert ai_pipeline.resume_id != de_pipeline.resume_id


async def test_jobs_are_isolated_per_pipeline_no_cross_contamination(repo):
    ai_resume = await _make_resume(repo, "AI Engineer resume")
    de_resume = await _make_resume(repo, "Data Engineer resume")
    ai_pipeline = await _make_pipeline(repo, ai_resume, name="AI Engineer pipeline")
    de_pipeline = await _make_pipeline(repo, de_resume, name="Data Engineer pipeline")

    await repo.upsert_job(_job_data(ai_pipeline, ai_resume, _uid="ai-1", title="AI Engineer I"))
    await repo.upsert_job(_job_data(ai_pipeline, ai_resume, _uid="ai-2", title="AI Engineer II"))
    await repo.upsert_job(_job_data(de_pipeline, de_resume, _uid="de-1", title="Data Engineer I"))

    ai_jobs = await repo.list_jobs(pipeline_id=ai_pipeline.id)
    de_jobs = await repo.list_jobs(pipeline_id=de_pipeline.id)

    assert {j.title for j in ai_jobs} == {"AI Engineer I", "AI Engineer II"}
    assert {j.title for j in de_jobs} == {"Data Engineer I"}
    assert all(j.scored_with_resume_id == ai_resume.id for j in ai_jobs)
    assert all(j.scored_with_resume_id == de_resume.id for j in de_jobs)

    all_jobs = await repo.list_jobs()
    assert len(all_jobs) == 3


async def test_pipeline_without_resume_is_extract_only_mode(repo):
    """FR-2.6: a pipeline may have no resume bound."""
    pipeline = await _make_pipeline(repo, resume=None, name="Market scan")
    assert pipeline.resume_id is None

    await repo.upsert_job(_job_data(pipeline, resume=None, _uid="scan-1", match_score=None))
    jobs = await repo.list_jobs(pipeline_id=pipeline.id)
    assert len(jobs) == 1
    assert jobs[0].scored_with_resume_id is None


# ── Resume deletion guard (FR-1A.7) ─────────────────────────────────────────


async def test_delete_resume_blocked_while_enabled_pipeline_references_it(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume, enabled=True)

    with pytest.raises(ResumeInUseError) as exc_info:
        await repo.delete_resume(resume.id)
    assert pipeline.name in str(exc_info.value)

    # Disabling the pipeline unblocks deletion.
    await repo.update_pipeline(pipeline.id, enabled=False)
    deleted = await repo.delete_resume(resume.id)
    assert deleted is True
    assert await repo.get_resume(resume.id) is None


async def test_delete_resume_with_no_pipelines_succeeds(repo):
    resume = await _make_resume(repo)
    assert await repo.delete_resume(resume.id) is True


# ── Job listing filters (parity with v1's api/routes/jobs.py) ──────────────


async def test_list_jobs_filters_and_sort(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    await repo.upsert_job(_job_data(pipeline, resume, _uid="1", title="Senior ML Engineer", match_score=0.9, company="Acme"))
    await repo.upsert_job(_job_data(pipeline, resume, _uid="2", title="Junior ML Engineer", match_score=0.3, company="Beta"))
    await repo.upsert_job(_job_data(pipeline, resume, _uid="3", title="Data Scientist", match_score=0.6, company="Acme"))

    high_scorers = await repo.list_jobs(min_score=0.5)
    assert {j.title for j in high_scorers} == {"Senior ML Engineer", "Data Scientist"}

    acme_only = await repo.list_jobs(company="acme")  # case-insensitive
    assert {j.title for j in acme_only} == {"Senior ML Engineer", "Data Scientist"}

    sorted_desc = await repo.list_jobs(sort_by="match_score")
    assert [j.match_score for j in sorted_desc] == [0.9, 0.6, 0.3]


async def test_list_jobs_excludes_deleted_unless_requested(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    job, _ = await repo.upsert_job(_job_data(pipeline, resume, _uid="1"))

    assert len(await repo.list_jobs()) == 1
    await repo.delete_job(job.id)
    assert len(await repo.list_jobs()) == 0
    assert len(await repo.list_jobs(status="deleted")) == 1


async def test_upsert_job_dedupes_by_link(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    link = "https://linkedin.com/jobs/dedupe-test"

    job1, is_new1 = await repo.upsert_job(_job_data(pipeline, resume, link=link, title="First pass"))
    job2, is_new2 = await repo.upsert_job(_job_data(pipeline, resume, link=link, title="Second pass (updated)"))

    assert is_new1 is True
    assert is_new2 is False
    assert job1.id == job2.id
    assert (await repo.get_job(job1.id)).title == "Second pass (updated)"
    assert len(await repo.list_jobs()) == 1


# ── Bulk delete by date (carried over feature, now on a real timestamptz) ──


async def test_count_and_delete_jobs_before_uses_date_posted_when_present(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    old_posted = datetime(2020, 1, 1, tzinfo=timezone.utc)
    recent_posted = datetime.now(timezone.utc)

    await repo.upsert_job(_job_data(pipeline, resume, _uid="old", date_posted=old_posted))
    await repo.upsert_job(_job_data(pipeline, resume, _uid="recent", date_posted=recent_posted))

    assert await repo.count_jobs_before(date(2021, 1, 1)) == 1
    deleted = await repo.delete_jobs_before(date(2021, 1, 1))
    assert deleted == 1
    assert len(await repo.list_jobs()) == 1


async def test_count_and_delete_jobs_before_falls_back_to_scraped_at(repo):
    """When date_posted is null, fall back to scraped_at (system-design.md §3)."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    old_scraped = datetime(2020, 1, 1, tzinfo=timezone.utc)
    await repo.upsert_job(_job_data(pipeline, resume, _uid="old-no-date", date_posted=None, scraped_at=old_scraped))
    await repo.upsert_job(_job_data(pipeline, resume, _uid="recent-no-date", date_posted=None, scraped_at=datetime.now(timezone.utc)))

    assert await repo.count_jobs_before(date(2021, 1, 1)) == 1
    deleted = await repo.delete_jobs_before(date(2021, 1, 1))
    assert deleted == 1
    remaining = await repo.list_jobs()
    assert len(remaining) == 1
    assert remaining[0].link.endswith("recent-no-date")


async def test_bulk_delete_by_date_composes_with_pipeline_filter(repo):
    """delete_jobs_before has no pipeline scoping itself (it's a global flush,
    matching v1's feature) — but list_jobs(pipeline_id=...) after the delete
    proves per-pipeline visibility still works correctly post-delete."""
    ai_resume = await _make_resume(repo, "AI resume")
    de_resume = await _make_resume(repo, "DE resume")
    ai_pipeline = await _make_pipeline(repo, ai_resume, name="AI pipeline")
    de_pipeline = await _make_pipeline(repo, de_resume, name="DE pipeline")

    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    recent = datetime.now(timezone.utc)
    await repo.upsert_job(_job_data(ai_pipeline, ai_resume, _uid="ai-old", date_posted=old))
    await repo.upsert_job(_job_data(ai_pipeline, ai_resume, _uid="ai-recent", date_posted=recent))
    await repo.upsert_job(_job_data(de_pipeline, de_resume, _uid="de-old", date_posted=old))

    await repo.delete_jobs_before(date(2021, 1, 1))

    assert len(await repo.list_jobs(pipeline_id=ai_pipeline.id)) == 1
    assert len(await repo.list_jobs(pipeline_id=de_pipeline.id)) == 0


# ── RejectedJob (FR-2.3) ─────────────────────────────────────────────────────


async def test_rejected_job_audit_trail(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    run = await repo.create_scrape_run(pipeline.id, config_snapshot={"query": pipeline.query})

    await repo.create_rejected_job(
        scrape_run_id=run.id,
        pipeline_id=pipeline.id,
        title="Underqualified role",
        company="Acme",
        link="https://linkedin.com/jobs/rejected-1",
        reason="below_threshold",
        match_score=0.1,
    )

    rejected = await repo.list_rejected_jobs(pipeline_id=pipeline.id)
    assert len(rejected) == 1
    assert rejected[0].reason == "below_threshold"

    # Never promoted to a real Job row.
    assert len(await repo.list_jobs(pipeline_id=pipeline.id)) == 0


async def test_delete_rejected_jobs_older_than_retention_window(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    run = await repo.create_scrape_run(pipeline.id, config_snapshot={})

    old_rejected = await repo.create_rejected_job(
        scrape_run_id=run.id, pipeline_id=pipeline.id, title="Old", company="X",
        link="https://x/1", reason="below_threshold",
    )
    # Backdate it directly (repository has no "created_at" override param by design).
    from sqlalchemy import update as sa_update
    from app.domain.models import RejectedJob

    await repo._s.execute(
        sa_update(RejectedJob).where(RejectedJob.id == old_rejected.id)
        .values(created_at=datetime.now(timezone.utc) - timedelta(days=40))
    )
    await repo._s.commit()

    await repo.create_rejected_job(
        scrape_run_id=run.id, pipeline_id=pipeline.id, title="Recent", company="X",
        link="https://x/2", reason="below_threshold",
    )

    deleted = await repo.delete_rejected_jobs_older_than(days=30)
    assert deleted == 1
    remaining = await repo.list_rejected_jobs(pipeline_id=pipeline.id)
    assert [r.title for r in remaining] == ["Recent"]


# ── ScrapeRun ─────────────────────────────────────────────────────────────────


async def test_scrape_run_lifecycle(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    run = await repo.create_scrape_run(pipeline.id, config_snapshot={"query": pipeline.query})
    assert run.status == "running"

    await repo.update_scrape_run(run.id, jobs_seen=5, jobs_saved=3, jobs_rejected=2)
    await repo.finish_scrape_run(run.id, status="completed")

    fetched = await repo.get_scrape_run(run.id)
    assert fetched.status == "completed"
    assert fetched.jobs_seen == 5
    assert fetched.finished_at is not None

    runs = await repo.list_scrape_runs(pipeline_id=pipeline.id)
    assert len(runs) == 1


# ── LLMSetting (FR-3.1 — single active row, global) ─────────────────────────


async def test_llm_setting_single_active_row(repo):
    assert await repo.get_active_llm_setting() is None

    first = await repo.set_active_llm_setting(provider="groq", model="llama-3.3-70b-versatile")
    assert first.provider == "groq"

    updated = await repo.set_active_llm_setting(provider="bedrock", model="mistral.mistral-large-2407-v1:0")
    assert updated.id == first.id  # same row, updated in place
    assert updated.provider == "bedrock"

    active = await repo.get_active_llm_setting()
    assert active.provider == "bedrock"
    assert active.model == "mistral.mistral-large-2407-v1:0"
