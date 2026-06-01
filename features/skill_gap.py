"""
Feature module: skill_gap
Aggregate skill gap analysis across all matched jobs.

Groups missing skills by frequency, assigns priority tiers,
and identifies the candidate's current strengths.
"""
from __future__ import annotations

from collections import Counter

from loguru import logger
from pydantic import BaseModel


class SkillGapEntry(BaseModel):
    skill: str
    frequency: int
    pct_jobs: float
    priority: str  # high | medium | low


class SkillGapAnalysis(BaseModel):
    total_jobs_analysed: int
    skill_gaps: list[SkillGapEntry]
    top_gap_areas: list[str]      # high-priority gaps
    your_strengths: list[str]     # skills matched in ≥40% of jobs


def analyse_skill_gaps(
    scored_jobs: list[dict],
    candidate_profile: dict,
    limit: int = 20,
) -> SkillGapAnalysis:
    """Aggregate missing skills from scored jobs and rank by frequency."""
    all_missing: list[str] = []
    all_matched: list[str] = []

    for job in scored_jobs:
        for s in (job.get("missing_skills") or []):
            if s:
                all_missing.append(s.lower().strip())
        for s in (job.get("matched_skills") or []):
            if s:
                all_matched.append(s.lower().strip())

    total_jobs = len(scored_jobs)
    if total_jobs == 0:
        return SkillGapAnalysis(
            total_jobs_analysed=0,
            skill_gaps=[],
            top_gap_areas=[],
            your_strengths=[],
        )

    missing_counts = Counter(all_missing)
    matched_counts = Counter(all_matched)

    gaps: list[SkillGapEntry] = []
    for skill, count in missing_counts.most_common(limit):
        pct = count / total_jobs
        priority = "high" if pct >= 0.6 else ("medium" if pct >= 0.3 else "low")
        gaps.append(
            SkillGapEntry(skill=skill, frequency=count, pct_jobs=round(pct, 3), priority=priority)
        )

    top_areas = [g.skill for g in gaps if g.priority == "high"][:5]
    strengths = [
        skill
        for skill, count in matched_counts.most_common(10)
        if count / total_jobs >= 0.4
    ]

    logger.debug(
        f"[SkillGap] {total_jobs} jobs → {len(gaps)} gaps, {len(strengths)} strengths"
    )

    return SkillGapAnalysis(
        total_jobs_analysed=total_jobs,
        skill_gaps=gaps,
        top_gap_areas=top_areas,
        your_strengths=strengths,
    )
