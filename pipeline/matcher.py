"""
JobMatcher — scores jobs against a candidate profile.

Weighted scoring formula (weights from config.yaml):
    score = 0.40 × semantic_similarity
          + 0.35 × skills_overlap
          + 0.15 × experience_match
          + 0.10 × title_match

Phase 3.  Phase 7: EmbeddingCache (diskcache) + single-batch encoding.
"""
from __future__ import annotations

import hashlib
from functools import cached_property
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger
from sklearn.metrics.pairwise import cosine_similarity

from config.settings import get_settings

settings = get_settings()

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "embedding_cache"


# ── Embedding cache ───────────────────────────────────────────────────────────

class EmbeddingCache:
    """
    Disk-backed embedding cache using diskcache.

    Key  = sha256(text)[:24]
    Value = np.ndarray (float32 vector)

    Falls back to no-cache mode if diskcache is not installed.
    ~5× faster on second pipeline runs when most JDs haven't changed.
    """

    def __init__(self, cache_dir: Path = _CACHE_DIR) -> None:
        self._cache = None
        try:
            import diskcache
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache = diskcache.Cache(str(cache_dir))
            logger.debug(f"[EmbeddingCache] Disk cache at {cache_dir}")
        except ImportError:
            logger.info("[EmbeddingCache] diskcache not installed — running without cache. "
                        "pip install diskcache to enable.")

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:24]

    def get(self, text: str) -> Optional[np.ndarray]:
        if self._cache is None:
            return None
        try:
            vec = self._cache.get(self._key(text))
            return np.array(vec, dtype=np.float32) if vec is not None else None
        except Exception:
            return None

    def set(self, text: str, vector: np.ndarray) -> None:
        if self._cache is None:
            return
        try:
            self._cache.set(self._key(text), vector.tolist())
        except Exception:
            pass

    def close(self) -> None:
        if self._cache is not None:
            try:
                self._cache.close()
            except Exception:
                pass


# ── Matcher ───────────────────────────────────────────────────────────────────

class JobMatcher:
    """
    Scores a list of parsed jobs against a candidate profile.

    Usage:
        matcher = JobMatcher()
        scored, gaps = matcher.score_all(parsed_jobs, candidate_profile, resume_text)
    """

    def __init__(self) -> None:
        cfg = settings.yaml_config.get("matching", {})
        self._model_name: str = cfg.get("embedding_model", "all-MiniLM-L6-v2")
        w = cfg.get("score_weights", {})
        self._w_semantic: float   = float(w.get("semantic_similarity", 0.40))
        self._w_skills: float     = float(w.get("skills_overlap", 0.35))
        self._w_experience: float = float(w.get("experience_match", 0.15))
        self._w_title: float      = float(w.get("title_match", 0.10))
        self._threshold: float    = float(cfg.get("min_score_threshold", 0.40))
        self._emb_cache = EmbeddingCache()

    @cached_property
    def _model(self):
        logger.info(f"[Matcher] Loading embedding model '{self._model_name}'…")
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(self._model_name)
        logger.info("[Matcher] Embedding model ready")
        return model

    def _embed_batch(self, texts: list[str]) -> np.ndarray:
        """
        Encode a batch of texts. Cache hits skip the model; misses are batch-encoded
        in a single model.encode() call and then stored.
        """
        vectors: list[Optional[np.ndarray]] = [self._emb_cache.get(t) for t in texts]
        miss_indices = [i for i, v in enumerate(vectors) if v is None]

        if miss_indices:
            miss_texts = [texts[i] for i in miss_indices]
            encoded = self._model.encode(
                miss_texts, convert_to_numpy=True, show_progress_bar=False, batch_size=32
            )
            for i, idx in enumerate(miss_indices):
                vectors[idx] = encoded[i]
                self._emb_cache.set(texts[idx], encoded[i])

            hits = len(texts) - len(miss_indices)
            logger.debug(
                f"[Matcher] Batch embed: {len(texts)} texts — "
                f"{hits} cache hits, {len(miss_indices)} encoded"
            )

        return np.vstack(vectors)

    # ── Individual scoring components ─────────────────────────────────────────

    def _skills_score(
        self,
        required_skills: list[str],
        candidate_skills: list[str],
    ) -> tuple[float, list[str], list[str]]:
        if not required_skills:
            return 0.5, [], []
        req = {s.lower().strip() for s in required_skills}
        cand = {s.lower().strip() for s in candidate_skills}
        matched = sorted(req & cand)
        missing = sorted(req - cand)
        return float(len(matched) / len(req)), matched, missing

    def _experience_score(
        self,
        required_min_years: Optional[int],
        candidate_years: Optional[float],
    ) -> float:
        if required_min_years is None:
            return 0.5
        if candidate_years is None:
            return 0.3
        gap = required_min_years - candidate_years
        if gap <= 0:   return 1.0
        elif gap <= 1: return 0.75
        elif gap <= 2: return 0.50
        elif gap <= 3: return 0.25
        else:          return 0.0

    # ── Main scoring entry points ─────────────────────────────────────────────

    def score_all(
        self,
        parsed_jobs: list[dict],
        candidate_profile: dict,
        resume_raw_text: str = "",
    ) -> tuple[list[dict], list[dict]]:
        """
        Score all jobs in a single batch-encoded pass.

        All unique texts (JD + titles + resume) are collected first, then encoded
        in one model.encode() call. Cache hits never reach the model.

        Returns (scored_jobs, skill_gaps).
        """
        logger.info(f"[Matcher] Scoring {len(parsed_jobs)} jobs (batch mode)…")

        candidate = {**candidate_profile, "_resume_raw_text": resume_raw_text}
        cand_skills = list(set(
            (candidate.get("skills") or []) +
            (candidate.get("tools") or []) +
            (candidate.get("languages") or [])
        ))
        cand_exp = candidate.get("total_experience_years")
        cand_title = candidate.get("current_title") or ""

        # ── Collect all unique texts for one batch encode ─────────────────────
        descriptions = [job.get("description") or "" for job in parsed_jobs]
        job_titles   = [job.get("title") or "" for job in parsed_jobs]
        all_texts = list(dict.fromkeys(
            descriptions + job_titles + [resume_raw_text, cand_title]
        ))
        # Pre-warm cache / encode everything at once
        self._embed_batch([t for t in all_texts if t])

        # ── Score each job (vectors now all in cache) ─────────────────────────
        scored: list[dict] = []
        all_missing: list[str] = []

        for job in parsed_jobs:
            try:
                result = self._score_job_cached(job, candidate, cand_skills, cand_exp, cand_title, resume_raw_text)
                scored.append(result)
                all_missing.extend(result.get("missing_skills", []))
            except Exception as e:
                logger.error(f"[Matcher] Error scoring job {job.get('id')}: {e}")
                scored.append({**job, "match_score": 0.0, "matched_skills": [], "missing_skills": []})

        scored.sort(key=lambda j: j.get("match_score", 0.0), reverse=True)
        skill_gap = self._compute_skill_gaps(all_missing, len(parsed_jobs))

        above = [j for j in scored if j.get("match_score", 0) >= self._threshold]
        logger.info(
            f"[Matcher] Done — top={scored[0]['match_score'] if scored else 0:.2%} "
            f"above_threshold={len(above)}/{len(scored)}"
        )
        return scored, skill_gap

    def _score_job_cached(
        self,
        job: dict,
        candidate: dict,
        cand_skills: list[str],
        cand_exp: Optional[float],
        cand_title: str,
        resume_raw_text: str,
    ) -> dict:
        description = job.get("description") or ""
        job_title   = job.get("title") or ""
        req_skills  = job.get("skills_required") or []
        req_exp_min = job.get("experience_years_min")

        # Semantic: JD vs resume (vectors already in cache)
        if description and resume_raw_text:
            vecs = self._embed_batch([description, resume_raw_text])
            sem = float(max(0.0, min(1.0, cosine_similarity(vecs[0:1], vecs[1:2])[0][0])))
        else:
            sem = 0.0

        # Title match (vectors already in cache)
        if job_title and cand_title:
            vecs = self._embed_batch([job_title, cand_title])
            title_sc = float(max(0.0, min(1.0, cosine_similarity(vecs[0:1], vecs[1:2])[0][0])))
        else:
            title_sc = 0.5

        skill_sc, matched, missing = self._skills_score(req_skills, cand_skills)
        exp_sc = self._experience_score(req_exp_min, cand_exp)

        total = round(float(max(0.0, min(1.0,
            self._w_semantic * sem
            + self._w_skills * skill_sc
            + self._w_experience * exp_sc
            + self._w_title * title_sc
        ))), 4)

        return {
            **job,
            "match_score": total,
            "matched_skills": matched,
            "missing_skills": missing,
            "score_breakdown": {
                "semantic":    round(sem, 4),
                "skills":      round(skill_sc, 4),
                "experience":  round(exp_sc, 4),
                "title":       round(title_sc, 4),
            },
        }

    @staticmethod
    def _compute_skill_gaps(missing_skills: list[str], total_jobs: int) -> list[dict]:
        from collections import Counter
        counts = Counter(missing_skills)
        return [
            {"skill": s, "frequency": c, "pct_jobs": round(c / total_jobs, 3) if total_jobs else 0}
            for s, c in counts.most_common(20)
        ]
