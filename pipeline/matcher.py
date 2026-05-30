"""
JobMatcher — scores jobs against a candidate profile.

Weighted scoring formula (weights from config.yaml):
    score = 0.40 × semantic_similarity
          + 0.35 × skills_overlap
          + 0.15 × experience_match
          + 0.10 × title_match

All components return floats in [0.0, 1.0].

Uses sentence-transformers all-MiniLM-L6-v2 (free, ~80MB, runs locally).
Model is loaded once and cached on the instance.

Phase 3.
"""
from __future__ import annotations

from functools import cached_property
from typing import Optional

import numpy as np
from loguru import logger
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import get_settings

settings = get_settings()


class JobMatcher:
    """
    Scores a list of parsed jobs against a candidate profile.

    Usage:
        matcher = JobMatcher()
        scored = matcher.score_all(parsed_jobs, candidate_profile)
    """

    def __init__(self) -> None:
        cfg = settings.yaml_config.get("matching", {})
        self._model_name: str = cfg.get("embedding_model", "all-MiniLM-L6-v2")
        w = cfg.get("score_weights", {})
        self._w_semantic: float    = float(w.get("semantic_similarity", 0.40))
        self._w_skills: float      = float(w.get("skills_overlap", 0.35))
        self._w_experience: float  = float(w.get("experience_match", 0.15))
        self._w_title: float       = float(w.get("title_match", 0.10))
        self._threshold: float     = float(cfg.get("min_score_threshold", 0.40))

    # ── Lazy-loaded embedding model ───────────────────────────────────────────

    @cached_property
    def _model(self):
        """Load sentence-transformers model once, cache for the lifetime of the instance."""
        logger.info(f"[Matcher] Loading embedding model '{self._model_name}'…")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(self._model_name)
        logger.info("[Matcher] Embedding model ready")
        return model

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Encode a list of strings into embedding vectors."""
        return self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    # ── Individual scoring components ─────────────────────────────────────────

    def _semantic_score(
        self,
        job_description: str,
        resume_text: str,
    ) -> float:
        """
        Cosine similarity between the full JD embedding and resume embedding.
        Returns a float in [0.0, 1.0].
        """
        if not job_description or not resume_text:
            return 0.0
        vecs = self._embed([job_description, resume_text])
        sim = cosine_similarity(vecs[0:1], vecs[1:2])[0][0]
        # cosine_similarity can return slightly negative for very dissimilar texts; clamp
        return float(max(0.0, min(1.0, sim)))

    def _skills_score(
        self,
        required_skills: list[str],
        candidate_skills: list[str],
    ) -> tuple[float, list[str], list[str]]:
        """
        Fraction of required skills present in the candidate profile.

        Returns:
            (score, matched_skills, missing_skills)
        """
        if not required_skills:
            return 0.5, [], []     # neutral if no skills listed

        req = {s.lower().strip() for s in required_skills}
        cand = {s.lower().strip() for s in candidate_skills}

        matched = sorted(req & cand)
        missing = sorted(req - cand)
        score = len(matched) / len(req)
        return float(score), matched, missing

    def _experience_score(
        self,
        required_min_years: Optional[int],
        candidate_years: Optional[float],
    ) -> float:
        """
        How well the candidate's years of experience meets the requirement.

        Scoring logic:
            - No requirement → 0.5 (neutral)
            - Candidate has no declared experience → 0.3 (unknown, slight penalty)
            - candidate_years >= required → 1.0
            - candidate_years is 1 year short → 0.75
            - candidate_years is 2 years short → 0.5
            - candidate_years is 3+ years short → linear decline to 0.0
        """
        if required_min_years is None:
            return 0.5
        if candidate_years is None:
            return 0.3

        gap = required_min_years - candidate_years
        if gap <= 0:
            return 1.0
        elif gap <= 1:
            return 0.75
        elif gap <= 2:
            return 0.50
        elif gap <= 3:
            return 0.25
        else:
            return 0.0

    def _title_score(
        self,
        job_title: str,
        candidate_title: Optional[str],
    ) -> float:
        """
        Semantic similarity between the job title and the candidate's current title.
        Returns a float in [0.0, 1.0].
        """
        if not job_title or not candidate_title:
            return 0.5    # neutral when title unknown
        vecs = self._embed([job_title, candidate_title])
        sim = cosine_similarity(vecs[0:1], vecs[1:2])[0][0]
        return float(max(0.0, min(1.0, sim)))

    # ── Main scoring entry points ─────────────────────────────────────────────

    def score_job(self, job: dict, candidate: dict) -> dict:
        """
        Score a single job dict against a candidate profile dict.

        Args:
            job:       parsed job dict (includes description, skills_required, etc.)
            candidate: ParsedResume.model_dump() dict

        Returns:
            job dict enriched with match_score, matched_skills, missing_skills,
            and score_breakdown sub-dict.
        """
        # Pull candidate data
        cand_skills = list(set(
            (candidate.get("skills") or []) +
            (candidate.get("tools") or []) +
            (candidate.get("languages") or [])
        ))
        cand_exp = candidate.get("total_experience_years")
        cand_title = candidate.get("current_title")

        # Pull job data
        req_skills = job.get("skills_required") or []
        req_exp_min = job.get("experience_years_min")
        job_title = job.get("title", "")
        description = job.get("description") or ""

        # Compute components
        sem = self._semantic_score(description, candidate.get("_resume_raw_text", ""))
        skill_sc, matched, missing = self._skills_score(req_skills, cand_skills)
        exp_sc = self._experience_score(req_exp_min, cand_exp)
        title_sc = self._title_score(job_title, cand_title)

        # Weighted total
        total = (
            self._w_semantic * sem
            + self._w_skills * skill_sc
            + self._w_experience * exp_sc
            + self._w_title * title_sc
        )
        total = round(float(max(0.0, min(1.0, total))), 4)

        return {
            **job,
            "match_score": total,
            "matched_skills": matched,
            "missing_skills": missing,
            "score_breakdown": {
                "semantic": round(sem, 4),
                "skills": round(skill_sc, 4),
                "experience": round(exp_sc, 4),
                "title": round(title_sc, 4),
            },
        }

    def score_all(
        self,
        parsed_jobs: list[dict],
        candidate_profile: dict,
        resume_raw_text: str = "",
    ) -> tuple[list[dict], list[dict]]:
        """
        Score all jobs and compute skill gaps.

        Args:
            parsed_jobs:      list of parsed job dicts
            candidate_profile: ParsedResume.model_dump()
            resume_raw_text:  raw resume text for semantic scoring

        Returns:
            (scored_jobs, skill_gaps)
            scored_jobs — sorted by match_score desc, filtered by threshold
            skill_gaps  — [{skill, frequency, pct_jobs}] sorted by frequency desc
        """
        logger.info(f"[Matcher] Scoring {len(parsed_jobs)} jobs…")

        # Attach raw text to candidate dict so score_job can use it
        candidate = {**candidate_profile, "_resume_raw_text": resume_raw_text}

        scored = []
        all_missing: list[str] = []

        for job in parsed_jobs:
            try:
                result = self.score_job(job, candidate)
                scored.append(result)
                all_missing.extend(result.get("missing_skills", []))
            except Exception as e:
                logger.error(f"[Matcher] Error scoring job {job.get('id')}: {e}")
                scored.append({**job, "match_score": 0.0, "matched_skills": [], "missing_skills": []})

        # Sort by match_score descending
        scored.sort(key=lambda j: j.get("match_score", 0.0), reverse=True)

        # Compute skill gaps (frequency across all jobs)
        skill_gap = self._compute_skill_gaps(all_missing, len(parsed_jobs))

        above_threshold = [j for j in scored if j.get("match_score", 0) >= self._threshold]
        below = len(scored) - len(above_threshold)

        logger.info(
            f"[Matcher] Done — "
            f"top score={scored[0]['match_score'] if scored else 0:.2%} | "
            f"above threshold={len(above_threshold)} | "
            f"filtered out={below}"
        )
        return scored, skill_gap

    @staticmethod
    def _compute_skill_gaps(missing_skills: list[str], total_jobs: int) -> list[dict]:
        """
        Aggregate missing skills across all jobs, rank by how often they appear.

        Returns list of dicts: [{skill, frequency, pct_jobs}]
        """
        from collections import Counter
        counts = Counter(missing_skills)
        return [
            {
                "skill": skill,
                "frequency": count,
                "pct_jobs": round(count / total_jobs, 3) if total_jobs else 0,
            }
            for skill, count in counts.most_common(20)  # top 20 gaps
        ]
