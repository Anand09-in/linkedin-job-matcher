"""
Unit tests for analyze_batch — LLM call mocked (system-design.md §6: "tested
with the LLM call mocked to return a fixed BatchJobAnalysis, verifying the
deterministic filter logic independently of any real model's behavior").
No Postgres, no Bedrock, no Playwright needed — these run in the `api` image.
"""
from __future__ import annotations

from app.llm_tasks.batch_extract import analyze_batch
from app.llm_tasks.schemas import BatchJobAnalysis, JobAnalysisResult, ResumeProfile
from app.scrapers.base import RawJob

_PROFILE = ResumeProfile(current_title="Engineer", total_experience_years=3, skills=["Python"], summary="...")


def _raw_job(i: int) -> RawJob:
    return RawJob(title=f"Job {i}", company="Acme", link=f"https://x/{i}", description="...")


class _FakeStructuredLLM:
    def __init__(self, response: BatchJobAnalysis):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response: BatchJobAnalysis):
        self._response = response

    def with_structured_output(self, schema):
        return self._structured(schema)

    def _structured(self, schema):
        return _FakeStructuredLLM(self._response)


async def test_analyze_batch_returns_llm_results_when_resume_present():
    jobs = [_raw_job(0), _raw_job(1)]
    fake_response = BatchJobAnalysis(
        results=[
            JobAnalysisResult(
                job_index=0, skills_required=["Python"], match_score=0.8,
                matched_skills=["Python"], match_rationale="Good fit",
            ),
            JobAnalysisResult(
                job_index=1, skills_required=["Go"], match_score=0.2,
                missing_skills=["Go"], match_rationale="Poor fit",
            ),
        ]
    )

    result = await analyze_batch(jobs, _PROFILE, _FakeLLM(fake_response))

    assert len(result.results) == 2
    assert result.results[0].match_score == 0.8
    assert result.results[1].match_score == 0.2


async def test_analyze_batch_forces_null_scores_when_no_resume_even_if_llm_ignores_instruction():
    """Defense in depth (system-design.md §3.3, extended): even if the LLM
    doesn't follow the "no resume -> don't score" prompt instruction, the
    CODE must not trust it — the system decides whether scoring even applies."""
    jobs = [_raw_job(0)]
    fake_response = BatchJobAnalysis(
        results=[
            JobAnalysisResult(
                job_index=0, skills_required=["Python"], match_score=0.75,
                matched_skills=["Python"], match_rationale="ignored the instruction",
            ),
        ]
    )

    result = await analyze_batch(jobs, None, _FakeLLM(fake_response))  # no resume profile

    assert result.results[0].match_score is None
    assert result.results[0].matched_skills == []
    assert result.results[0].missing_skills == []
    assert result.results[0].match_rationale is None
    # Extraction fields are untouched — only match-related fields are forced.
    assert result.results[0].skills_required == ["Python"]


async def test_analyze_batch_empty_batch_short_circuits_without_calling_llm():
    class _ExplodingLLM:
        def with_structured_output(self, schema):
            raise AssertionError("should not be called for an empty batch")

    result = await analyze_batch([], _PROFILE, _ExplodingLLM())
    assert result.results == []


async def test_analyze_batch_passes_through_result_count_mismatch_without_raising():
    """A batch of 2 but the LLM only returns 1 result — logged as a warning
    (see the function's own logic), not a hard failure; scrape_service.py
    handles the missing job_index by rejecting that specific job."""
    jobs = [_raw_job(0), _raw_job(1)]
    fake_response = BatchJobAnalysis(results=[JobAnalysisResult(job_index=0, match_score=0.5)])

    result = await analyze_batch(jobs, _PROFILE, _FakeLLM(fake_response))
    assert len(result.results) == 1


def test_skill_lists_are_truncated_when_the_model_overproduces():
    """
    Confirmed live against real Bedrock during Phase 3 testing: a prose-only
    "keep it concise" instruction wasn't enough — Mistral Large spiraled into
    a 280+ item skills_required list for some inputs (once even degenerating
    into an unrelated thesaurus of adjectives). The schema's max_length=8
    gives the model a structural signal, but this validator is the actual
    backstop: truncate rather than trust, regardless of what the model does.
    """
    oversized = [f"skill-{i}" for i in range(300)]
    result = JobAnalysisResult(
        job_index=0,
        skills_required=oversized,
        skills_nice_to_have=oversized,
        matched_skills=oversized,
        missing_skills=oversized,
    )

    assert len(result.skills_required) == 8
    assert len(result.skills_nice_to_have) == 8
    assert len(result.matched_skills) == 8
    assert len(result.missing_skills) == 8
    assert result.skills_required == [f"skill-{i}" for i in range(8)]


def test_skill_lists_within_limit_are_left_untouched():
    result = JobAnalysisResult(job_index=0, skills_required=["Python", "AWS"])
    assert result.skills_required == ["Python", "AWS"]
