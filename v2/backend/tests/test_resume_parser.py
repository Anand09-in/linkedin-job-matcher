"""
Unit tests for parse_resume — LLM call mocked, same pattern as
test_batch_extract.py. No Postgres, no Bedrock needed.
"""
from __future__ import annotations

from app.llm_tasks.resume_parser import parse_resume
from app.llm_tasks.schemas import ResumeProfile


class _FakeStructuredLLM:
    def __init__(self, response: ResumeProfile):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response: ResumeProfile):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._response)


async def test_parse_resume_returns_llm_profile():
    fake_profile = ResumeProfile(
        current_title="AI/ML Engineer",
        total_experience_years=1.5,
        skills=["Python", "PyTorch", "AWS", "Kafka"],
        summary="AI/ML engineer with production experience in LLM and streaming systems.",
    )

    result = await parse_resume("... raw resume text ...", _FakeLLM(fake_profile))

    assert result.current_title == "AI/ML Engineer"
    assert result.total_experience_years == 1.5
    assert "PyTorch" in result.skills


def test_resume_profile_skills_are_truncated_when_the_model_overproduces():
    """Same defensive backstop as JobAnalysisResult's skill lists — see
    that class's docstring for why a schema max_length alone isn't trusted
    to be enough."""
    oversized = [f"skill-{i}" for i in range(300)]
    profile = ResumeProfile(skills=oversized)
    assert len(profile.skills) == 25
    assert profile.skills == [f"skill-{i}" for i in range(25)]
