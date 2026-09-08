"""Unit tests for synthesize_salary — LLM call mocked, same pattern as
test_batch_extract.py. No Postgres, no Bedrock, no web search needed."""
from __future__ import annotations

from app.llm_tasks.salary_synthesis import synthesize_salary
from app.llm_tasks.schemas import SalaryBenchmark


class _FakeStructuredLLM:
    def __init__(self, response: SalaryBenchmark):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response: SalaryBenchmark):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._response)


async def test_synthesize_salary_returns_llm_result():
    fake = SalaryBenchmark(
        min_amount=1200000, max_amount=1800000, currency="INR", period="annual",
        confidence="medium", source_note="Based on 3 relevant listings for similar roles in Bangalore.",
    )

    result = await synthesize_salary(
        job_title="Data Engineer", company="Acme", location="Bangalore, India",
        experience_years_min=2, search_results_text="[Data Engineer salary Bangalore]: 12-18 LPA...",
        llm=_FakeLLM(fake),
    )

    assert result.min_amount == 1200000
    assert result.currency == "INR"
    assert result.confidence == "medium"


async def test_synthesize_salary_with_no_search_results_still_returns_a_result():
    """Sparse/empty search results is a normal case, not an error — the LLM
    is expected to say so via confidence="low", not raise."""
    fake = SalaryBenchmark(confidence="low", source_note="No relevant search results were found.", currency="USD")

    result = await synthesize_salary(
        job_title="Obscure Title", company="Unknown Co", location=None,
        experience_years_min=None, search_results_text="", llm=_FakeLLM(fake),
    )

    assert result.confidence == "low"
    assert result.min_amount is None
