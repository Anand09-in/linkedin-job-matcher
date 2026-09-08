"""
Orchestration tests for salary_service.py and referral_service.py — web
search and LLM synthesis both mocked, verifying the query-building and
wiring between them (system-design.md §6 pattern: mock the LLM, test the
deterministic logic around it).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.llm_tasks.schemas import ReferralSearchResult, SalaryBenchmark
from app.services import referral_service, salary_service


async def test_get_salary_benchmark_includes_location_and_experience_in_query():
    """Direct check of the concern that shaped this feature: salary varies
    by location and experience, so the search query must include both, not
    just the job title."""
    fake_benchmark = SalaryBenchmark(confidence="medium", source_note="test", currency="USD")

    with patch("app.services.salary_service.web_search", AsyncMock(return_value=[])) as mock_search, \
         patch("app.services.salary_service.synthesize_salary", AsyncMock(return_value=fake_benchmark)):
        await salary_service.get_salary_benchmark(
            job_title="Data Engineer", company="Acme", location="Bangalore, India",
            experience_years_min=2, llm=object(),
        )

    query = mock_search.call_args.args[0]
    assert "Data Engineer" in query
    assert "Acme" in query
    assert "Bangalore" in query
    assert "2+ years" in query


async def test_get_salary_benchmark_handles_missing_location_and_experience():
    """Both are optional — the query must still be well-formed without them."""
    fake_benchmark = SalaryBenchmark(confidence="low", source_note="test", currency="USD")

    with patch("app.services.salary_service.web_search", AsyncMock(return_value=[])) as mock_search, \
         patch("app.services.salary_service.synthesize_salary", AsyncMock(return_value=fake_benchmark)):
        result = await salary_service.get_salary_benchmark(
            job_title="Engineer", company="Acme", location=None, experience_years_min=None, llm=object(),
        )

    assert result.confidence == "low"
    query = mock_search.call_args.args[0]
    assert "None" not in query


async def test_find_referral_contacts_scopes_search_to_company_linkedin_profiles():
    """Confirms the query is a public-web search for LinkedIn profile pages
    (site:linkedin.com/in), NOT any LinkedIn API/scrape call — this is the
    concrete difference between the two data-source options presented to
    the user, verified at the query-construction level."""
    fake_result = ReferralSearchResult(contacts=[])

    with patch("app.services.referral_service.web_search", AsyncMock(return_value=[])) as mock_search, \
         patch("app.services.referral_service.synthesize_referral_contacts", AsyncMock(return_value=fake_result)):
        await referral_service.find_referral_contacts(company="Acme", job_title="Data Engineer", llm=object())

    query = mock_search.call_args.args[0]
    assert "site:linkedin.com/in" in query
    assert "Acme" in query
    assert "Data Engineer" in query
