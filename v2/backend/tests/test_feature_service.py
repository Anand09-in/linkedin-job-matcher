"""
Integration tests for feature_service.run_feature against real Postgres (via
conftest's `repo` fixture) — the individual LLM calls are mocked (covered on
their own in test_feature_llm_tasks.py), so these exercise FR-6.3's actual
exit criterion: a second IDENTICAL request is served from the cache without
a new LLM call, verified by call count, not just response shape. Also covers
FR-1A.8 (resume comes from the job's own pipeline) and the
needs-a-resume / unknown-feature / job-not-found error paths.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.exceptions import FeatureRequiresResumeError, UnknownFeatureError
from app.llm_tasks.schemas import (
    AllFeaturesResult,
    CompanyResearchResult,
    CoverLetterResult,
    InterviewPrepResult,
    ReferralSearchResult,
    ResumeImprovementResult,
)
from app.services.feature_service import run_all_features, run_feature


async def _make_resume(repo):
    resume = await repo.create_resume(name="R", filename="r.txt", raw_text="Full resume text.")
    await repo.update_resume_parsed_profile(
        resume.id,
        {"summary": "Data engineer.", "skills": ["Python", "Spark"], "current_title": "Data Engineer", "total_experience_years": 3.0},
    )
    return await repo.get_resume(resume.id)


async def _make_job(repo, resume_id=None):
    pipeline = await repo.create_pipeline(name="P", site="linkedin", query="Data Engineer", resume_id=resume_id)
    job, _ = await repo.upsert_job(
        {
            "title": "Data Engineer", "company": "Acme", "location": "Bangalore, India",
            "link": f"https://x/{uuid.uuid4()}", "pipeline_id": pipeline.id, "source_site": pipeline.site,
            "match_score": 0.8 if resume_id else None,
        }
    )
    return job


async def test_cover_letter_cache_hit_skips_second_llm_call(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake_result = CoverLetterResult(cover_letter="A cover letter.")

    with patch("app.services.feature_service.generate_cover_letter", AsyncMock(return_value=fake_result)) as mock_call:
        first = await run_feature(repo, "cover_letter", job.id, {}, llm=object())
        second = await run_feature(repo, "cover_letter", job.id, {}, llm=object())

    assert mock_call.await_count == 1
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["result"]["cover_letter"] == "A cover letter."


async def test_cover_letter_different_tone_is_a_cache_miss(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake_result = CoverLetterResult(cover_letter="A cover letter.")

    with patch("app.services.feature_service.generate_cover_letter", AsyncMock(return_value=fake_result)) as mock_call:
        await run_feature(repo, "cover_letter", job.id, {"tone": "professional"}, llm=object())
        await run_feature(repo, "cover_letter", job.id, {"tone": "confident"}, llm=object())

    assert mock_call.await_count == 2


async def test_cover_letter_regenerate_bypasses_cache(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake_result = CoverLetterResult(cover_letter="A cover letter.")

    with patch("app.services.feature_service.generate_cover_letter", AsyncMock(return_value=fake_result)) as mock_call:
        await run_feature(repo, "cover_letter", job.id, {}, llm=object())
        await run_feature(repo, "cover_letter", job.id, {}, llm=object(), regenerate=True)

    assert mock_call.await_count == 2


async def test_feature_requiring_resume_raises_when_pipeline_has_none(repo):
    job = await _make_job(repo, resume_id=None)

    with pytest.raises(FeatureRequiresResumeError):
        await run_feature(repo, "cover_letter", job.id, {}, llm=object())


async def test_company_research_works_without_a_resume(repo):
    """FR-2.6-style extract-only pipeline: company_research is the one
    Phase 6 feature that doesn't need a resume at all."""
    job = await _make_job(repo, resume_id=None)
    fake_result = CompanyResearchResult(overall_impression="A mid-size data-focused company.")

    with patch("app.services.feature_service.research_company", AsyncMock(return_value=fake_result)):
        result = await run_feature(repo, "company_research", job.id, {}, llm=object())

    assert result["cached"] is False
    assert result["result"]["overall_impression"] == "A mid-size data-focused company."


async def test_referral_search_works_without_a_resume(repo):
    """Phase 7 addition: referral_search (finding contacts) doesn't need a
    resume either — it's about the job's company/title, same as
    company_research."""
    job = await _make_job(repo, resume_id=None)
    fake_result = ReferralSearchResult(caveat="test", contacts=[])
    fake_llm = object()

    with patch("app.services.feature_service.find_referral_contacts", AsyncMock(return_value=fake_result)) as mock_call:
        result = await run_feature(repo, "referral_search", job.id, {}, llm=fake_llm)

    mock_call.assert_awaited_once_with("Acme", "Data Engineer", fake_llm)
    assert result["cached"] is False
    assert result["result"]["caveat"] == "test"


async def test_unknown_feature_raises(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)

    with pytest.raises(UnknownFeatureError):
        await run_feature(repo, "ats_score", job.id, {}, llm=object())


async def test_job_not_found_raises(repo):
    with pytest.raises(LookupError):
        await run_feature(repo, "cover_letter", uuid.uuid4(), {}, llm=object())


def _fake_all_features_result() -> AllFeaturesResult:
    return AllFeaturesResult(
        cover_letter=CoverLetterResult(cover_letter="Dear Hiring Manager,\n\nBody.\n\nSincerely,"),
        interview_prep=InterviewPrepResult(questions=[], prep_tips=[]),
        company_research=CompanyResearchResult(overall_impression="Looks solid."),
        resume_improvement=ResumeImprovementResult(overall_fit_grade="B", summary_rewrite="Rewritten summary."),
    )


async def test_all_features_makes_exactly_one_llm_call(repo):
    """The whole point of run_all_features: one combined call populates all
    four, not four independent ones."""
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake = _fake_all_features_result()

    with patch("app.services.feature_service.generate_all_features", AsyncMock(return_value=fake)) as mock_call:
        result = await run_all_features(repo, job.id, tone="confident", word_count=200, llm=object())

    mock_call.assert_awaited_once()
    assert result["cached"] is False
    assert result["results"]["cover_letter"]["cover_letter"].startswith("Dear Hiring Manager")
    assert result["results"]["company_research"]["overall_impression"] == "Looks solid."


async def test_all_features_populates_the_same_per_feature_cache_run_feature_reads(repo):
    """The other half of the point: a later single-feature call (e.g. the
    Job Detail page's per-tab "Regenerate") must hit the SAME cache entries
    the bundle just wrote, not miss and trigger a redundant standalone call."""
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake = _fake_all_features_result()

    with patch("app.services.feature_service.generate_all_features", AsyncMock(return_value=fake)):
        await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object())

    with patch("app.services.feature_service.research_company", AsyncMock()) as mock_standalone:
        standalone = await run_feature(repo, "company_research", job.id, {}, llm=object())

    mock_standalone.assert_not_awaited()
    assert standalone["cached"] is True
    assert standalone["result"]["overall_impression"] == "Looks solid."


async def test_all_features_cache_hit_skips_the_llm_entirely(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake = _fake_all_features_result()

    with patch("app.services.feature_service.generate_all_features", AsyncMock(return_value=fake)) as mock_call:
        first = await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object())
        second = await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object())

    mock_call.assert_awaited_once()
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["results"] == first["results"]


async def test_all_features_regenerate_bypasses_cache(repo):
    resume = await _make_resume(repo)
    job = await _make_job(repo, resume_id=resume.id)
    fake = _fake_all_features_result()

    with patch("app.services.feature_service.generate_all_features", AsyncMock(return_value=fake)) as mock_call:
        await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object())
        await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object(), regenerate=True)

    assert mock_call.await_count == 2


async def test_all_features_raises_when_pipeline_has_no_resume(repo):
    job = await _make_job(repo, resume_id=None)

    with pytest.raises(FeatureRequiresResumeError):
        await run_all_features(repo, job.id, tone="professional", word_count=250, llm=object())
