"""
Integration tests for run_scrape_pipeline against real Postgres (via
conftest's `repo` fixture) with a fake scraper adapter and a mocked
analyze_batch — exercising the exact Phase 3 exit criteria from plan.md:

  - a real-shaped run produces Job rows with populated match scores/fields
    in one pass, no second matching step
  - a deliberately-broken batch does not abort the run
  - two pipelines with different resumes don't bleed into each other
"""
from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, patch

from app.llm_tasks.schemas import BatchJobAnalysis, JobAnalysisResult, ResumeProfile
from app.scrapers.base import RawJob
from app.services.scrape_service import run_scrape_pipeline


def _raw_job(uid: str, title: str = "Engineer", company: str = "Acme") -> RawJob:
    return RawJob(title=title, company=company, link=f"https://x/{uid}", description=f"JD for {uid}")


class _FakeScraper:
    """Yields pre-baked batches — ignores ScrapeConfig entirely, since these
    tests are about scrape_service's orchestration, not any real adapter."""

    def __init__(self, batches: list[list[RawJob]]):
        self._batches = batches

    async def scrape(self, config):
        for batch in self._batches:
            yield batch


async def _make_resume(repo, name: str = "Resume"):
    return await repo.create_resume(name=name, filename=f"{name}.txt", raw_text=f"resume text for {name}")


async def _make_pipeline(repo, resume, **overrides):
    kwargs = dict(name="Pipeline", site="linkedin", query="Engineer", resume_id=resume.id if resume else None)
    kwargs.update(overrides)
    return await repo.create_pipeline(**kwargs)


def _patch_scraper(batches: list[list[RawJob]]):
    return patch("app.services.scrape_service.get_scraper", return_value=_FakeScraper(batches))


def _patch_llm():
    return patch("app.services.scrape_service.get_llm", AsyncMock(return_value=object()))


class _FakeArqRedis:
    """Records enqueue_job calls instead of touching real Redis — used to
    verify salary_lookup_task gets enqueued after each save (FR-5.1)
    without needing a real arq worker/Redis connection in these tests."""

    def __init__(self):
        self.enqueued: list[tuple] = []

    async def enqueue_job(self, task_name: str, *args):
        self.enqueued.append((task_name, *args))


def _fake_profile_for(raw_text: str) -> ResumeProfile:
    """Deterministic, traceable-back-to-source fake profile — lets tests
    assert which resume's text actually reached the parse step without
    needing a real LLM call."""
    return ResumeProfile(summary=raw_text, skills=["Python"], total_experience_years=1.0)


def _patch_parse_resume(call_log: Optional[list] = None):
    """Mocks the ONE-TIME resume-parsing call (resume_parser.parse_resume) —
    every test with a resume bound needs this patched, since a fresh test
    resume always has an empty parsed_profile and _resolve_resume_profile
    will call parse_resume for it exactly once per run (see
    test_resume_profile_is_parsed_once_and_cached for that behavior itself)."""

    async def fake_parse_resume(raw_text, llm):
        if call_log is not None:
            call_log.append(raw_text)
        return _fake_profile_for(raw_text)

    return patch("app.services.scrape_service.parse_resume", fake_parse_resume)


async def test_run_produces_job_rows_with_scores_in_one_pass(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    jobs = [_raw_job("a"), _raw_job("b")]

    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, skills_required=["Python"], match_score=0.9, matched_skills=["Python"], match_rationale="great fit"),
            JobAnalysisResult(job_index=1, skills_required=["Go"], match_score=0.9, matched_skills=["Go"], match_rationale="great fit"),
        ]
    )

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["status"] == "completed"
    assert result["jobs_seen"] == 2
    assert result["jobs_saved"] == 2
    assert result["jobs_rejected"] == 0

    saved = await repo.list_jobs(pipeline_id=pipeline.id)
    assert len(saved) == 2
    assert all(j.match_score == 0.9 for j in saved)
    assert all(j.scored_with_resume_id == resume.id for j in saved)
    assert all(j.pipeline_id == pipeline.id for j in saved)


async def test_duplicate_job_index_in_llm_response_last_one_wins(repo):
    """Confirmed against a REAL Bedrock (Mistral Large) call during Phase 3
    testing: for a 2-job batch, the model occasionally returns 3 results — a
    malformed draft job_index=0 followed by the two correct ones. Reassembly
    is a dict keyed by job_index, so the later, correct entry silently wins.
    Locking that in as intentional behavior, not an accident of dict order."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    jobs = [_raw_job("a"), _raw_job("b")]

    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, skills_required=["garbled", "malformed draft"], match_score=0.01),
            JobAnalysisResult(job_index=0, skills_required=["Python"], match_score=0.9, matched_skills=["Python"]),
            JobAnalysisResult(job_index=1, match_score=0.9),
        ]
    )

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["jobs_saved"] == 2
    assert result["jobs_rejected"] == 0
    saved = {j.link: j for j in await repo.list_jobs(pipeline_id=pipeline.id)}
    job_a = saved[jobs[0].link]
    assert job_a.match_score == 0.9
    assert job_a.skills_required == ["Python"]


async def test_jobs_below_threshold_are_rejected_not_saved(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume, min_match_score_override=0.5)
    jobs = [_raw_job("a"), _raw_job("b")]

    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, match_score=0.9),
            JobAnalysisResult(job_index=1, match_score=0.1),
        ]
    )

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["jobs_saved"] == 1
    assert result["jobs_rejected"] == 1
    rejected = await repo.list_rejected_jobs(pipeline_id=pipeline.id)
    assert rejected[0].reason == "below_match_score_threshold"


async def test_max_experience_override_rejects_overqualified_requirement(repo):
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume, max_experience_years_override=3)
    jobs = [_raw_job("junior"), _raw_job("senior")]

    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, match_score=0.9, experience_years_min=2),
            JobAnalysisResult(job_index=1, match_score=0.9, experience_years_min=8),
        ]
    )

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["jobs_saved"] == 1
    assert result["jobs_rejected"] == 1
    rejected = await repo.list_rejected_jobs(pipeline_id=pipeline.id)
    assert rejected[0].reason == "exceeds_max_experience_years"


async def test_broken_batch_does_not_abort_the_run(repo):
    """Phase 3 exit criterion: a deliberately-broken batch (mocked LLM
    failure) is confirmed not to abort the run."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    good_batch = [_raw_job("good")]
    bad_batch = [_raw_job("bad")]
    good_analysis = BatchJobAnalysis(results=[JobAnalysisResult(job_index=0, match_score=0.9)])

    async def fake_analyze(jobs, resume_profile, llm):
        if jobs[0].link.endswith("/bad"):
            raise RuntimeError("simulated LLM failure")
        return good_analysis

    with _patch_scraper([bad_batch, good_batch]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", fake_analyze):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["status"] == "completed"  # the RUN did not fail
    assert result["jobs_saved"] == 1
    assert result["jobs_rejected"] == 1
    assert len(result["errors"]) == 1

    rejected = await repo.list_rejected_jobs(pipeline_id=pipeline.id)
    assert rejected[0].reason == "llm_batch_failed"
    saved = await repo.list_jobs(pipeline_id=pipeline.id)
    assert len(saved) == 1
    assert saved[0].link.endswith("/good")


async def test_scraper_adapter_failure_marks_run_failed(repo):
    """The OTHER failure mode (system-design.md §1.1): the adapter itself
    can't reach the site at all -> the whole run fails, unlike a batch-level
    LLM failure which only rejects that batch."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    class _BrokenScraper:
        async def scrape(self, config):
            raise ConnectionError("simulated: can't reach the site")
            yield  # pragma: no cover — makes this an async generator

    with patch("app.services.scrape_service.get_scraper", return_value=_BrokenScraper()), \
         _patch_llm(), _patch_parse_resume():
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["status"] == "failed"
    assert result["jobs_saved"] == 0
    assert len(result["errors"]) == 1


async def test_resume_profile_parse_failure_marks_run_failed(repo):
    """The profile-resolution step is a run-setup prerequisite, same tier as
    an adapter failure — not a per-batch concern, so it fails the whole run
    rather than silently falling back to unscored/extract-only mode (which
    would be a surprising, silent behavior change from what the user set up)."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)

    async def failing_parse_resume(raw_text, llm):
        raise RuntimeError("simulated: resume parsing failed")

    with _patch_scraper([[_raw_job("a")]]), _patch_llm(), \
         patch("app.services.scrape_service.parse_resume", failing_parse_resume):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["status"] == "failed"
    assert result["jobs_saved"] == 0
    assert len(result["errors"]) == 1


async def test_resume_profile_is_parsed_once_and_cached(repo):
    """This is the actual behavior a real usage question was about: does
    the LLM need to "know" the resume on every batch call? Answer: the
    (comparatively expensive) full-resume parse happens ONCE per resume,
    ever — cached in Resume.parsed_profile — not once per run and not once
    per batch. Confirmed here by running the SAME pipeline twice and
    checking parse_resume was only actually invoked the first time."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    analysis = BatchJobAnalysis(results=[JobAnalysisResult(job_index=0, match_score=0.8)])
    parse_calls: list[str] = []

    with _patch_scraper([[_raw_job("a")]]), _patch_llm(), _patch_parse_resume(parse_calls), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        await run_scrape_pipeline(repo, pipeline)

    assert len(parse_calls) == 1  # parsed on the first run

    # Second run of the SAME pipeline/resume — even with a batch inside it,
    # parse_resume must not be called again; the cached profile is reused.
    with _patch_scraper([[_raw_job("b")]]), _patch_llm(), _patch_parse_resume(parse_calls), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        await run_scrape_pipeline(repo, pipeline)

    assert len(parse_calls) == 1  # still 1 — not called again on the second run

    cached = await repo.get_resume(resume.id)
    assert cached.parsed_profile is not None
    assert cached.parsed_profile["summary"] == resume.raw_text


async def test_two_pipelines_different_resumes_no_bleed_through(repo):
    ai_resume = await _make_resume(repo, "AI resume")
    de_resume = await _make_resume(repo, "DE resume")
    ai_pipeline = await _make_pipeline(repo, ai_resume, name="AI pipeline", query="AI Engineer")
    de_pipeline = await _make_pipeline(repo, de_resume, name="DE pipeline", query="Data Engineer")

    ai_jobs = [_raw_job("ai-1", title="AI Engineer")]
    de_jobs = [_raw_job("de-1", title="Data Engineer")]
    analysis = BatchJobAnalysis(results=[JobAnalysisResult(job_index=0, match_score=0.8)])

    seen_profiles: list[ResumeProfile] = []

    async def fake_analyze(jobs, resume_profile, llm):
        seen_profiles.append(resume_profile)
        return analysis

    with _patch_scraper([ai_jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", fake_analyze):
        await run_scrape_pipeline(repo, ai_pipeline)

    with _patch_scraper([de_jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", fake_analyze):
        await run_scrape_pipeline(repo, de_pipeline)

    # Each pipeline's profile traces back to ITS OWN resume's raw text
    # (via _fake_profile_for's summary=raw_text), not the other pipeline's.
    assert seen_profiles[0].summary == ai_resume.raw_text
    assert seen_profiles[1].summary == de_resume.raw_text
    assert seen_profiles[0].summary != seen_profiles[1].summary

    ai_saved = await repo.list_jobs(pipeline_id=ai_pipeline.id)
    de_saved = await repo.list_jobs(pipeline_id=de_pipeline.id)
    assert len(ai_saved) == 1 and ai_saved[0].scored_with_resume_id == ai_resume.id
    assert len(de_saved) == 1 and de_saved[0].scored_with_resume_id == de_resume.id


async def test_extract_only_mode_saves_all_jobs_unscored(repo):
    """FR-2.6: a pipeline with no resume bound runs extract-only — no filter applies."""
    pipeline = await _make_pipeline(repo, resume=None, name="Market scan")
    jobs = [_raw_job("a"), _raw_job("b")]

    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, skills_required=["Python"]),
            JobAnalysisResult(job_index=1, skills_required=["Go"]),
        ]
    )

    with _patch_scraper([jobs]), _patch_llm(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)

    assert result["jobs_saved"] == 2
    assert result["jobs_rejected"] == 0
    saved = await repo.list_jobs(pipeline_id=pipeline.id)
    assert all(j.match_score is None for j in saved)
    assert all(j.scored_with_resume_id is None for j in saved)


async def test_salary_lookup_enqueued_for_every_saved_job_not_rejected_ones(repo):
    """Phase 4 (FR-5.1): every job that actually gets SAVED triggers a
    fire-and-forget salary_lookup_task — rejected jobs never do, since they
    never become a Job row to enrich."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume, min_match_score_override=0.5)
    jobs = [_raw_job("pass"), _raw_job("fail")]
    analysis = BatchJobAnalysis(
        results=[
            JobAnalysisResult(job_index=0, match_score=0.9),  # passes -> saved
            JobAnalysisResult(job_index=1, match_score=0.1),  # rejected -> no Job row
        ]
    )
    fake_redis = _FakeArqRedis()

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        await run_scrape_pipeline(repo, pipeline, arq_redis=fake_redis)

    assert len(fake_redis.enqueued) == 1
    task_name, job_id = fake_redis.enqueued[0]
    assert task_name == "salary_lookup_task"

    saved = await repo.list_jobs(pipeline_id=pipeline.id)
    assert len(saved) == 1
    assert job_id == str(saved[0].id)


async def test_no_salary_lookup_enqueued_when_arq_redis_not_provided(repo):
    """arq_redis is optional — callers/tests that don't care about salary
    enrichment (like every other test in this file) shouldn't need to fake
    a redis pool just to run a scrape."""
    resume = await _make_resume(repo)
    pipeline = await _make_pipeline(repo, resume)
    jobs = [_raw_job("a")]
    analysis = BatchJobAnalysis(results=[JobAnalysisResult(job_index=0, match_score=0.9)])

    with _patch_scraper([jobs]), _patch_llm(), _patch_parse_resume(), \
         patch("app.services.scrape_service.analyze_batch", AsyncMock(return_value=analysis)):
        result = await run_scrape_pipeline(repo, pipeline)  # no arq_redis passed

    assert result["jobs_saved"] == 1  # completes normally, no error
