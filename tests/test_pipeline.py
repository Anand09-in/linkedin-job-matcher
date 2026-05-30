"""
Phase 3 tests — pipeline nodes, JobMatcher, and graph structure.

Run with:
    pytest tests/test_pipeline.py -v

No real LLM calls, no LinkedIn, no AWS — everything is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def make_parsed_job(**overrides) -> dict:
    base = {
        "id": "job-001",
        "title": "Senior Machine Learning Engineer",
        "company": "Acme AI",
        "location": "Bangalore, India",
        "link": "https://linkedin.com/jobs/view/001",
        "description": (
            "We need a Senior ML Engineer with 5+ years in Python, PyTorch, "
            "TensorFlow. Strong LLM and MLOps background. Docker and AWS required."
        ),
        "skills_required": ["python", "pytorch", "tensorflow", "llms", "docker", "aws"],
        "skills_nice_to_have": ["rust", "cuda"],
        "experience_years": "5+ years",
        "experience_years_min": 5,
        "seniority_level": "Senior",
        "employment_type": "Full-time",
        "remote_policy": "Hybrid",
        "match_score": None,
        "matched_skills": None,
        "missing_skills": None,
        "status": "new",
        "scraped_at": "2024-06-01T00:00:00",
    }
    return {**base, **overrides}


def make_candidate_profile(**overrides) -> dict:
    base = {
        "name": "Jane Smith",
        "current_title": "ML Engineer",
        "total_experience_years": 4.0,
        "skills": ["machine learning", "deep learning", "nlp", "llms"],
        "tools": ["python", "pytorch", "docker", "mlflow"],
        "languages": ["python", "sql"],
        "certifications": ["AWS ML Specialty"],
        "work_history": [
            {"title": "ML Engineer", "company": "StartupX", "duration_years": 4.0, "description": "..."}
        ],
        "education": [{"degree": "B.Tech", "institution": "IIT", "year": 2020, "field": "CS"}],
    }
    return {**base, **overrides}


# ─────────────────────────────────────────────────────────────────────────────
# JobMatcher unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestJobMatcher:

    def _make_matcher(self, monkeypatch) -> "JobMatcher":
        """Create a JobMatcher with a mocked embedding model."""
        from pipeline.matcher import JobMatcher

        # Patch the yaml_config to return test weights
        monkeypatch.setattr(
            "pipeline.matcher.settings",
            MagicMock(yaml_config={
                "matching": {
                    "embedding_model": "all-MiniLM-L6-v2",
                    "score_weights": {
                        "semantic_similarity": 0.40,
                        "skills_overlap": 0.35,
                        "experience_match": 0.15,
                        "title_match": 0.10,
                    },
                    "min_score_threshold": 0.40,
                }
            })
        )
        matcher = JobMatcher()

        # Mock the embedding model so tests don't need sentence-transformers
        mock_model = MagicMock()
        # Return deterministic vectors: first call gets JD vector, second gets resume vector
        mock_model.encode.side_effect = lambda texts, **kw: np.array([
            [0.9, 0.1, 0.0] for _ in texts
        ])
        # Use object.__setattr__ to bypass cached_property
        object.__setattr__(matcher, "_model", mock_model)
        return matcher

    def test_skills_score_full_match(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        score, matched, missing = matcher._skills_score(
            ["python", "pytorch", "docker"],
            ["python", "pytorch", "docker", "tensorflow"],
        )
        assert score == 1.0
        assert "python" in matched
        assert missing == []

    def test_skills_score_partial_match(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        score, matched, missing = matcher._skills_score(
            ["python", "pytorch", "kubernetes", "rust"],
            ["python", "pytorch"],
        )
        assert score == 0.5
        assert "python" in matched
        assert "kubernetes" in missing
        assert "rust" in missing

    def test_skills_score_no_requirements(self, monkeypatch):
        """No required skills → neutral score of 0.5."""
        matcher = self._make_matcher(monkeypatch)
        score, matched, missing = matcher._skills_score([], ["python"])
        assert score == 0.5

    def test_experience_score_exceeds_requirement(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(3, 5.0) == 1.0

    def test_experience_score_exactly_meets(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(5, 5.0) == 1.0

    def test_experience_score_one_year_short(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(5, 4.0) == 0.75

    def test_experience_score_two_years_short(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(5, 3.0) == 0.50

    def test_experience_score_no_requirement(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(None, 4.0) == 0.5

    def test_experience_score_unknown_candidate(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        assert matcher._experience_score(5, None) == 0.3

    def test_score_job_returns_enriched_dict(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        job = make_parsed_job()
        candidate = make_candidate_profile()

        result = matcher.score_job(job, candidate)

        assert "match_score" in result
        assert "matched_skills" in result
        assert "missing_skills" in result
        assert "score_breakdown" in result
        assert 0.0 <= result["match_score"] <= 1.0
        assert isinstance(result["matched_skills"], list)
        assert isinstance(result["missing_skills"], list)

    def test_score_job_matched_skills_subset_of_required(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        job = make_parsed_job(skills_required=["python", "pytorch", "rust"])
        candidate = make_candidate_profile(
            tools=["python", "pytorch"],
            skills=[],
            languages=[],
        )
        result = matcher.score_job(job, candidate)
        assert "python" in result["matched_skills"]
        assert "pytorch" in result["matched_skills"]
        assert "rust" in result["missing_skills"]

    def test_score_all_sorted_by_score(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        jobs = [
            make_parsed_job(id="job-1", skills_required=["python"]),
            make_parsed_job(id="job-2", skills_required=["cobol", "fortran", "pascal"]),
        ]
        candidate = make_candidate_profile(
            tools=["python"], skills=[], languages=[]
        )
        scored, gaps = matcher.score_all(jobs, candidate)
        # Results should be sorted descending by match_score
        scores = [j["match_score"] for j in scored]
        assert scores == sorted(scores, reverse=True)

    def test_score_all_computes_skill_gaps(self, monkeypatch):
        matcher = self._make_matcher(monkeypatch)
        jobs = [
            make_parsed_job(id="j1", skills_required=["python", "kubernetes"]),
            make_parsed_job(id="j2", skills_required=["python", "kubernetes", "rust"]),
        ]
        candidate = make_candidate_profile(tools=["python"], skills=[], languages=[])
        _, gaps = matcher.score_all(jobs, candidate)
        gap_skills = [g["skill"] for g in gaps]
        assert "kubernetes" in gap_skills   # appears in 2 jobs
        assert gaps[0]["frequency"] >= gaps[-1]["frequency"]   # sorted descending

    def test_compute_skill_gaps_frequency(self, monkeypatch):
        from pipeline.matcher import JobMatcher
        result = JobMatcher._compute_skill_gaps(
            ["python", "kubernetes", "python", "rust", "kubernetes", "kubernetes"],
            total_jobs=3,
        )
        assert result[0]["skill"] == "kubernetes"
        assert result[0]["frequency"] == 3
        assert result[0]["pct_jobs"] == 1.0

    def test_score_job_weighted_formula(self, monkeypatch):
        """Score should equal the weighted sum of components."""
        matcher = self._make_matcher(monkeypatch)
        job = make_parsed_job(
            skills_required=["python"],      # 1 required skill
            experience_years_min=3,
        )
        candidate = make_candidate_profile(
            tools=["python"], skills=[], languages=[],
            total_experience_years=5.0,     # exceeds requirement
            current_title="ML Engineer",
        )
        result = matcher.score_job(job, candidate)
        bd = result["score_breakdown"]

        expected = (
            0.40 * bd["semantic"]
            + 0.35 * bd["skills"]
            + 0.15 * bd["experience"]
            + 0.10 * bd["title"]
        )
        assert abs(result["match_score"] - round(expected, 4)) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# Graph structure tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphStructure:

    def test_build_graph_compiles(self):
        """Graph should compile without errors."""
        from pipeline.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_graph_has_correct_nodes(self):
        """All 4 nodes should be present."""
        from pipeline.graph import build_graph
        graph = build_graph()
        # LangGraph compiled graph exposes nodes via graph.nodes dict
        node_names = set(graph.nodes.keys())
        assert "scraper" in node_names
        assert "jd_parser" in node_names
        assert "resume_parser" in node_names
        assert "matcher" in node_names

    def test_get_graph_singleton(self):
        """get_graph() should return the same instance on repeated calls."""
        import pipeline.graph as pg
        pg._graph_instance = None   # reset singleton

        from pipeline.graph import get_graph
        g1 = get_graph()
        g2 = get_graph()
        assert g1 is g2


# ─────────────────────────────────────────────────────────────────────────────
# Node unit tests (mocked dependencies)
# ─────────────────────────────────────────────────────────────────────────────

class TestScraperNode:

    def test_scraper_node_returns_raw_jobs(self, monkeypatch):
        """scraper_node should return raw_jobs from a mocked DB."""
        mock_job = MagicMock()
        mock_job.to_dict.return_value = make_parsed_job()

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = [mock_job]

        mock_session_factory = MagicMock(return_value=mock_session)

        with patch("pipeline.nodes.create_engine"), \
             patch("pipeline.nodes.sessionmaker", return_value=mock_session_factory), \
             patch("pipeline.nodes.get_settings"):
            from pipeline.nodes import scraper_node
            result = scraper_node({"errors": []})

        assert "raw_jobs" in result
        assert len(result["raw_jobs"]) == 1

    def test_scraper_node_handles_db_error(self, monkeypatch):
        """DB failure should return empty raw_jobs and add to errors."""
        with patch("pipeline.nodes.create_engine", side_effect=Exception("DB down")):
            from pipeline.nodes import scraper_node
            result = scraper_node({"errors": []})

        assert result["raw_jobs"] == []
        assert len(result["errors"]) > 0


class TestJDParserNode:

    def test_skips_already_parsed_jobs(self, monkeypatch):
        """Jobs with skills_required already set should not be re-parsed."""
        mock_llm = MagicMock()
        mock_parser = MagicMock()

        with patch("pipeline.nodes.get_llm", return_value=mock_llm), \
             patch("pipeline.nodes.JDParser", return_value=mock_parser), \
             patch("pipeline.nodes.SyncSession"):
            from pipeline.nodes import jd_parser_node
            state = {
                "raw_jobs": [
                    make_parsed_job(skills_required=["python"]),  # already parsed
                ],
                "errors": [],
            }
            result = jd_parser_node(state)

        # LLM parser should NOT have been called
        mock_parser.parse.assert_not_called()
        assert len(result["parsed_jobs"]) == 1

    def test_parses_jobs_without_skills(self, monkeypatch):
        """Jobs with no skills_required should be sent to the JDParser."""
        from parser.schemas import ParsedJD

        mock_parsed = ParsedJD(
            skills_required=["python", "pytorch"],
            experience_years_min=3,
        )
        mock_parser_instance = MagicMock()
        mock_parser_instance.parse.return_value = mock_parsed

        mock_sync_session = MagicMock()
        mock_sync_session.__enter__ = lambda s: s
        mock_sync_session.__exit__ = MagicMock(return_value=False)
        mock_sync_session.return_value = MagicMock(
            update_job_parsed_fields=MagicMock()
        )

        with patch("pipeline.nodes.get_llm"), \
             patch("pipeline.nodes.JDParser", return_value=mock_parser_instance), \
             patch("pipeline.nodes.SyncSession", return_value=mock_sync_session):
            from pipeline.nodes import jd_parser_node
            state = {
                "raw_jobs": [make_parsed_job(skills_required=None)],
                "errors": [],
            }
            result = jd_parser_node(state)

        mock_parser_instance.parse.assert_called_once()
        assert len(result["parsed_jobs"]) == 1


class TestMatcherNode:

    def test_matcher_node_returns_scored_jobs(self, monkeypatch):
        """matcher_node should call JobMatcher and return scored jobs."""
        job = make_parsed_job()
        candidate = make_candidate_profile()

        scored_job = {**job, "match_score": 0.78, "matched_skills": ["python"], "missing_skills": []}
        mock_matcher = MagicMock()
        mock_matcher.score_all.return_value = ([scored_job], [{"skill": "rust", "frequency": 1}])

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("pipeline.nodes.JobMatcher", return_value=mock_matcher), \
             patch("pipeline.nodes.SyncSession", return_value=mock_session):
            from pipeline.nodes import matcher_node
            result = matcher_node({
                "parsed_jobs": [job],
                "candidate_profile": candidate,
                "resume_text": "John Smith ML Engineer 4 years Python PyTorch",
                "errors": [],
            })

        assert "scored_jobs" in result
        assert len(result["scored_jobs"]) == 1
        assert result["scored_jobs"][0]["match_score"] == 0.78
        assert len(result["skill_gaps"]) == 1

    def test_matcher_node_empty_jobs(self, monkeypatch):
        """Empty job list should return empty scored_jobs without error."""
        from pipeline.nodes import matcher_node
        result = matcher_node({"parsed_jobs": [], "candidate_profile": {}, "errors": []})
        assert result["scored_jobs"] == []

    def test_matcher_node_empty_profile_adds_error(self, monkeypatch):
        """Missing candidate profile should add to errors but not crash."""
        from pipeline.nodes import matcher_node
        result = matcher_node({
            "parsed_jobs": [make_parsed_job()],
            "candidate_profile": {},
            "errors": [],
        })
        assert len(result["errors"]) > 0
