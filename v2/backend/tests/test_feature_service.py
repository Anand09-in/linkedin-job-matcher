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
from app.llm_tasks.schemas import CompanyResearchResult, CoverLetterResult, ReferralSearchResult
from app.services.feature_service import run_feature


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
