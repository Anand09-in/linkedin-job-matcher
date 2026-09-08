"""Unit tests for the Phase 6 on-demand feature LLM calls — same pattern as
test_salary_synthesis.py / test_batch_extract.py: a fake structured-output
LLM, no Postgres, no Bedrock, no web search."""
from __future__ import annotations

from app.llm_tasks.company_research import research_company
from app.llm_tasks.cover_letter import generate_cover_letter
from app.llm_tasks.interview_prep import generate_interview_prep
from app.llm_tasks.negotiation_prep import prepare_negotiation
from app.llm_tasks.referral_message import draft_referral_message
from app.llm_tasks.resume_improvement import improve_resume
from app.llm_tasks.schemas import (
    CompanyResearchResult,
    CoverLetterResult,
    InterviewPrepResult,
    InterviewQuestion,
    JobContext,
    NegotiationPrepResult,
    ReferralMessageResult,
    ResumeContext,
    ResumeImprovementResult,
    ResumeSuggestion,
)


class _FakeStructuredLLM:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._response)


def _job(**overrides) -> JobContext:
    defaults = dict(
        title="Data Engineer", company="Acme", location="Bangalore, India",
        seniority_level="Mid", employment_type="Full-time", remote_policy="Hybrid",
        description="Build data pipelines with Spark and Airflow.",
        skills_required=["Python", "Spark", "Airflow"], skills_nice_to_have=["Kafka"],
        matched_skills=["Python", "Spark"], missing_skills=["Airflow"],
        salary_benchmark={"min_amount": 1200000, "max_amount": 1800000, "currency": "INR", "confidence": "medium", "source_note": "test"},
    )
    defaults.update(overrides)
    return JobContext(**defaults)


def _resume(**overrides) -> ResumeContext:
    defaults = dict(
        current_title="Data Engineer", total_experience_years=3.0,
        skills=["Python", "Spark", "SQL"], summary="Data engineer with 3 years experience.",
        raw_text="Full resume text goes here.",
    )
    defaults.update(overrides)
    return ResumeContext(**defaults)


async def test_generate_cover_letter():
    fake = CoverLetterResult(cover_letter="Paragraph one.\n\nParagraph two.\n\nParagraph three.")
    result = await generate_cover_letter(_job(), _resume(), "confident", _FakeLLM(fake))
    assert "Paragraph one" in result.cover_letter


async def test_generate_interview_prep():
    fake = InterviewPrepResult(
        questions=[
            InterviewQuestion(category="technical", question="How do you use Airflow?", answer_framework="deep-dive", key_points=["a", "b"])
        ],
        prep_tips=["Research Acme's engineering blog."],
    )
    result = await generate_interview_prep(_job(), _resume(), _FakeLLM(fake))
    assert result.questions[0].category == "technical"
    assert result.prep_tips == ["Research Acme's engineering blog."]


async def test_research_company_does_not_need_a_resume():
    fake = CompanyResearchResult(
        domain="saas", size_hint="mid-size", tech_stack_hints=["Spark"], culture_signals=["fast-paced"],
        green_flags=["clear tech stack"], red_flags=[], overall_impression="Looks like a solid mid-size data team.",
    )
    result = await research_company(_job(), _FakeLLM(fake))
    assert result.overall_impression == "Looks like a solid mid-size data team."
    assert result.red_flags == []


async def test_improve_resume():
    fake = ResumeImprovementResult(
        overall_fit_grade="B",
        suggestions=[ResumeSuggestion(section="Skills", priority="high", issue="Airflow missing", suggestion="Add Airflow")],
        keywords_to_add=["Airflow"],
        summary_rewrite="Data engineer skilled in Python and Spark, learning Airflow.",
        top_actions=["Add 'Airflow' to Skills section"],
    )
    result = await improve_resume(_job(), _resume(), _FakeLLM(fake))
    assert result.overall_fit_grade == "B"
    assert "Airflow" in result.keywords_to_add


async def test_draft_referral_message_with_named_contact():
    fake = ReferralMessageResult(message="Hi Jane, I saw you're a Data Engineer at Acme — I'm exploring a similar role there and would love to connect.")
    result = await draft_referral_message(
        _job(), _resume(), _FakeLLM(fake), channel="linkedin_connection_note", contact_name="Jane Doe", contact_title="Data Engineer"
    )
    assert "Jane" in result.message


async def test_prepare_negotiation_uses_salary_benchmark():
    fake = NegotiationPrepResult(
        assessment="Your 3 years of experience puts you mid-band for this range.",
        target_ask="1,500,000 INR",
        talking_points=["Strong Spark experience matches the JD directly."],
        scripts=["Based on my research, I was expecting a range closer to X."],
        risks_to_avoid=["Don't give a number before they do."],
    )
    result = await prepare_negotiation(_job(), _resume(), _FakeLLM(fake))
    assert result.target_ask == "1,500,000 INR"


def test_interview_prep_drops_truncated_questions_instead_of_raising():
    """Real bug found live (Phase 6): under the default token budget, Mistral
    Large truncated the 9th of 12 questions mid-item, leaving only
    {"category": "system_design"} — question/answer_framework missing.
    Pydantic would otherwise raise and crash the whole feature call over one
    bad item (see InterviewPrepResult._sanitize_questions's docstring and
    config.llm_interview_prep_max_tokens, which fixes the root cause; this
    validator is the defensive backstop for whenever it still happens)."""
    result = InterviewPrepResult(
        questions=[
            {"category": "technical", "question": "Explain X.", "answer_framework": "deep-dive", "key_points": ["a"]},
            {"category": "system_design"},  # truncated mid-item, exactly like the live failure
        ],
        prep_tips=[],
    )
    assert len(result.questions) == 1
    assert result.questions[0].category == "technical"


def test_interview_prep_tips_are_capped_independently_of_questions():
    """Pre-existing bug caught while fixing the above: a shared validator
    capped BOTH questions and prep_tips at 12, but prep_tips' own schema
    max_length is 5 — split into separate validators so each list is capped
    at its own declared limit."""
    result = InterviewPrepResult(questions=[], prep_tips=[f"tip {i}" for i in range(8)])
    assert len(result.prep_tips) == 5


async def test_prepare_negotiation_without_a_benchmark_still_returns_a_result():
    """No salary_benchmark on the job (still pending/failed) is a normal
    case — the prompt tells the model to give strategy-only advice, not an
    error; this test just proves the plumbing works with salary_benchmark=None."""
    fake = NegotiationPrepResult(
        assessment="No salary data is available yet, so here is general strategy advice instead.",
        target_ask=None,
        talking_points=["Anchor on your relevant Spark/Python experience."],
    )
    result = await prepare_negotiation(_job(salary_benchmark=None), _resume(), _FakeLLM(fake))
    assert result.target_ask is None
