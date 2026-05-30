"""
Phase 2 tests for JDParser, ResumeParser, and ParsedJD/ParsedResume schemas.

Run with:
    pytest tests/test_parser.py -v

No real LLM calls — all tests use mock LLM responses.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from parser.schemas import CompanyInfo, EducationEntry, ParsedJD, ParsedResume, WorkHistoryEntry


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_JD = """
We are looking for a Senior Machine Learning Engineer to join our AI team.

Requirements:
- 5+ years of experience in machine learning and deep learning
- Expert in Python, PyTorch, TensorFlow
- Strong knowledge of LLMs, transformers, BERT, GPT architectures
- Experience with MLOps: MLflow, Kubeflow, or similar
- Familiarity with AWS SageMaker or GCP Vertex AI
- Docker and Kubernetes experience preferred
- Nice to have: Rust, C++, CUDA

Responsibilities:
- Design and implement ML models at scale
- Lead a team of 3-5 ML engineers
- Collaborate with product and data teams

This is a full-time hybrid role based in Bangalore. Salary: 25-40 LPA.
We're a Series B fintech startup with 200 employees.
"""

SAMPLE_RESUME = """
John Doe
Machine Learning Engineer
john.doe@email.com | Bangalore, India | linkedin.com/in/johndoe

SUMMARY
ML Engineer with 4 years of experience building NLP and CV systems at scale.

EXPERIENCE
Senior ML Engineer — Startup X (2022 – Present, 2 years)
  Built LLM-powered document processing pipeline using LangChain and OpenAI GPT-4.

ML Engineer — Company Y (2020 – 2022, 2 years)
  Developed real-time recommendation system using PyTorch and Kafka.

SKILLS
Machine Learning, Deep Learning, NLP, Computer Vision, LLMs

TOOLS & FRAMEWORKS
Python, PyTorch, TensorFlow, LangChain, Docker, AWS SageMaker, Kafka, MLflow

EDUCATION
B.Tech Computer Science — IIT Bombay (2020)

CERTIFICATIONS
AWS Certified ML Specialty
"""

SAMPLE_LLM_JD_RESPONSE = {
    "skills_required": ["Python", "PyTorch", "TensorFlow", "LLMs", "Transformers", "MLflow", "Docker"],
    "skills_nice_to_have": ["Rust", "C++", "CUDA", "Kubeflow"],
    "experience_years": "5+ years",
    "experience_years_min": 5,
    "seniority_level": "Senior",
    "employment_type": "Full-time",
    "remote_policy": "Hybrid",
    "education_required": None,
    "salary_range": "25-40 LPA",
    "responsibilities": [
        "Design and implement ML models at scale",
        "Lead a team of 3-5 ML engineers",
        "Collaborate with product and data teams",
    ],
    "company_info": {"size_hint": "startup", "domain": "fintech"},
}

SAMPLE_LLM_RESUME_RESPONSE = {
    "name": "John Doe",
    "current_title": "Senior ML Engineer",
    "total_experience_years": 4.0,
    "summary": "ML Engineer with 4 years of experience building NLP and CV systems.",
    "skills": ["Machine Learning", "Deep Learning", "NLP", "Computer Vision", "LLMs"],
    "tools": ["PyTorch", "TensorFlow", "LangChain", "Docker", "Kafka", "MLflow", "AWS SageMaker"],
    "languages": ["Python"],
    "certifications": ["AWS Certified ML Specialty"],
    "work_history": [
        {"title": "Senior ML Engineer", "company": "Startup X", "duration_years": 2.0,
         "description": "Built LLM-powered document processing pipeline"},
        {"title": "ML Engineer", "company": "Company Y", "duration_years": 2.0,
         "description": "Real-time recommendation system"},
    ],
    "education": [
        {"degree": "B.Tech", "institution": "IIT Bombay", "year": 2020, "field": "Computer Science"}
    ],
}


def make_mock_llm(response_dict: dict) -> MagicMock:
    """Create a mock LLM that returns a given dict as JSON."""
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = json.dumps(response_dict)
    mock_llm.invoke.return_value = mock_response
    return mock_llm


# ─────────────────────────────────────────────────────────────────────────────
# ParsedJD schema tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParsedJDSchema:

    def test_valid_full_response(self):
        jd = ParsedJD.model_validate(SAMPLE_LLM_JD_RESPONSE)
        assert jd.seniority_level == "Senior"
        assert jd.employment_type == "Full-time"
        assert jd.experience_years_min == 5
        assert "python" in jd.skills_required   # normalised to lowercase

    def test_skills_normalised_to_lowercase(self):
        jd = ParsedJD.model_validate({
            "skills_required": ["Python", "AWS S3", "  PyTorch  "],
            "skills_nice_to_have": ["CUDA"],
        })
        assert "python" in jd.skills_required
        assert "aws s3" in jd.skills_required
        assert "pytorch" in jd.skills_required
        assert "cuda" in jd.skills_nice_to_have

    def test_empty_skills_default(self):
        jd = ParsedJD.model_validate({})
        assert jd.skills_required == []
        assert jd.skills_nice_to_have == []

    def test_seniority_normalisation(self):
        cases = [
            ("senior engineer", "Senior"),
            ("Mid-Level", "Mid"),
            ("Entry Level", "Entry"),
            ("LEAD", "Lead"),
            ("staff engineer", "Lead"),  # staff maps to Lead
        ]
        for raw, expected in cases:
            jd = ParsedJD.model_validate({"seniority_level": raw})
            assert jd.seniority_level == expected, f"Failed for {raw!r}"

    def test_experience_min_coercion(self):
        jd = ParsedJD.model_validate({"experience_years_min": "3"})
        assert jd.experience_years_min == 3
        assert isinstance(jd.experience_years_min, int)

    def test_experience_min_invalid_returns_none(self):
        jd = ParsedJD.model_validate({"experience_years_min": "five years"})
        assert jd.experience_years_min is None

    def test_company_info_nested(self):
        jd = ParsedJD.model_validate(SAMPLE_LLM_JD_RESPONSE)
        assert jd.company_info.size_hint == "startup"
        assert jd.company_info.domain == "fintech"

    def test_all_nulls_valid(self):
        """Minimal JD with all nulls should not raise."""
        jd = ParsedJD.model_validate({
            "skills_required": [],
            "skills_nice_to_have": [],
            "experience_years": None,
            "seniority_level": None,
        })
        assert jd.skills_required == []


# ─────────────────────────────────────────────────────────────────────────────
# ParsedResume schema tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParsedResumeSchema:

    def test_valid_full_response(self):
        r = ParsedResume.model_validate(SAMPLE_LLM_RESUME_RESPONSE)
        assert r.name == "John Doe"
        assert r.total_experience_years == 4.0
        assert "python" in r.languages
        assert len(r.work_history) == 2
        assert len(r.education) == 1

    def test_skills_normalised(self):
        r = ParsedResume.model_validate({
            "skills": ["Machine Learning", "NLP"],
            "tools": ["PyTorch", "AWS SageMaker"],
            "languages": ["Python", "SQL"],
        })
        assert "machine learning" in r.skills
        assert "pytorch" in r.tools
        assert "python" in r.languages

    def test_all_skills_property(self):
        r = ParsedResume.model_validate({
            "skills": ["deep learning"],
            "tools": ["pytorch"],
            "languages": ["python"],
        })
        all_s = r.all_skills
        assert "deep learning" in all_s
        assert "pytorch" in all_s
        assert "python" in all_s

    def test_experience_years_coercion(self):
        r = ParsedResume.model_validate({"total_experience_years": "3.5"})
        assert r.total_experience_years == 3.5
        assert isinstance(r.total_experience_years, float)

    def test_experience_years_invalid_returns_none(self):
        r = ParsedResume.model_validate({"total_experience_years": "not a number"})
        assert r.total_experience_years is None

    def test_work_history_entries(self):
        r = ParsedResume.model_validate(SAMPLE_LLM_RESUME_RESPONSE)
        assert r.work_history[0].title == "Senior ML Engineer"
        assert r.work_history[0].duration_years == 2.0

    def test_education_entries(self):
        r = ParsedResume.model_validate(SAMPLE_LLM_RESUME_RESPONSE)
        assert r.education[0].degree == "B.Tech"
        assert r.education[0].year == 2020


# ─────────────────────────────────────────────────────────────────────────────
# JDParser integration tests (mock LLM)
# ─────────────────────────────────────────────────────────────────────────────

class TestJDParser:

    def _make_parser(self, response_dict: dict):
        from parser.jd_parser import JDParser
        return JDParser(llm=make_mock_llm(response_dict))

    def test_parse_returns_parsed_jd(self):
        parser = self._make_parser(SAMPLE_LLM_JD_RESPONSE)
        result = parser.parse(SAMPLE_JD)
        assert isinstance(result, ParsedJD)
        assert result.seniority_level == "Senior"
        assert len(result.skills_required) > 0

    def test_parse_empty_description_returns_empty(self):
        parser = self._make_parser(SAMPLE_LLM_JD_RESPONSE)
        result = parser.parse("")
        assert isinstance(result, ParsedJD)
        assert result.skills_required == []

    def test_parse_strips_markdown_fences(self):
        """LLM sometimes wraps JSON in ```json ... ``` — parser should strip it."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "```json\n" + json.dumps(SAMPLE_LLM_JD_RESPONSE) + "\n```"
        mock_llm.invoke.return_value = mock_response

        from parser.jd_parser import JDParser
        parser = JDParser(llm=mock_llm)
        result = parser.parse(SAMPLE_JD)
        assert result.seniority_level == "Senior"

    def test_parse_returns_empty_on_invalid_json(self):
        """Bad JSON from LLM should not crash — return empty ParsedJD."""
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "This is not valid JSON at all!"
        mock_llm.invoke.return_value = mock_response

        from parser.jd_parser import JDParser
        parser = JDParser(llm=mock_llm)
        result = parser.parse(SAMPLE_JD)
        assert isinstance(result, ParsedJD)
        assert result.skills_required == []

    def test_parse_batch(self):
        parser = self._make_parser(SAMPLE_LLM_JD_RESPONSE)
        descriptions = [SAMPLE_JD, SAMPLE_JD, SAMPLE_JD]
        results = parser.parse_batch(descriptions)
        assert len(results) == 3
        assert all(isinstance(r, ParsedJD) for r in results)

    def test_long_description_truncated(self):
        """Descriptions over 16k chars should be truncated before LLM call."""
        mock_llm = make_mock_llm(SAMPLE_LLM_JD_RESPONSE)
        from parser.jd_parser import JDParser
        parser = JDParser(llm=mock_llm)
        long_desc = "x" * 20_000
        parser.parse(long_desc)   # should not raise
        # Verify LLM was called with truncated text
        call_args = mock_llm.invoke.call_args
        user_message = call_args[0][0][1].content
        assert len(user_message) < 20_000


# ─────────────────────────────────────────────────────────────────────────────
# ResumeParser tests
# ─────────────────────────────────────────────────────────────────────────────

class TestResumeParser:

    def _make_parser(self, response_dict: dict):
        from parser.resume_parser import ResumeParser
        return ResumeParser(llm=make_mock_llm(response_dict))

    def test_parse_returns_parsed_resume(self):
        parser = self._make_parser(SAMPLE_LLM_RESUME_RESPONSE)
        result = parser.parse(SAMPLE_RESUME)
        assert isinstance(result, ParsedResume)
        assert result.name == "John Doe"
        assert result.total_experience_years == 4.0

    def test_parse_empty_text_raises(self):
        parser = self._make_parser(SAMPLE_LLM_RESUME_RESPONSE)
        with pytest.raises(ValueError, match="empty"):
            parser.parse("")

    def test_parse_strips_markdown_fences(self):
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "```\n" + json.dumps(SAMPLE_LLM_RESUME_RESPONSE) + "\n```"
        mock_llm.invoke.return_value = mock_response

        from parser.resume_parser import ResumeParser
        parser = ResumeParser(llm=mock_llm)
        result = parser.parse(SAMPLE_RESUME)
        assert result.name == "John Doe"

    def test_clean_text_removes_extra_whitespace(self):
        from parser.resume_parser import ResumeParser
        dirty = "Hello\n\n\n\n\nWorld\x00Null"
        clean = ResumeParser._clean_text(dirty)
        assert "\x00" not in clean
        assert "\n\n\n" not in clean

    def test_extract_text_from_bytes_real_pdf(self, tmp_path):
        """
        If pymupdf is installed, test extraction with a minimal real PDF.
        Skipped if pymupdf not installed.
        """
        pytest.importorskip("fitz")

        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "John Doe\nMachine Learning Engineer\n4 years experience")
        pdf_bytes = doc.tobytes()
        doc.close()

        from parser.resume_parser import ResumeParser
        parser = ResumeParser.__new__(ResumeParser)
        text = parser.extract_text(pdf_bytes)
        assert "John Doe" in text
        assert "Machine Learning" in text

    def test_all_skills_property_combines_correctly(self):
        parser = self._make_parser(SAMPLE_LLM_RESUME_RESPONSE)
        result = parser.parse(SAMPLE_RESUME)
        all_s = result.all_skills
        assert "python" in all_s
        assert "pytorch" in all_s
        assert "machine learning" in all_s
