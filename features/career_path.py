"""
Feature module: career_path  (Phase 6.8)
The most ambitious module. Uses resume + near-miss jobs + skill gap frequency
to output three time horizons and a prioritised learning roadmap.

Time horizons:
  now      — roles you can apply for today (match_score >= 0.65)
  6_months — near-miss roles (0.40 <= score < 0.65) + skills needed to reach them
  2_years  — stretch roles inferred from trajectory + full learning roadmap
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

_NOW_THRESHOLD      = 0.65
_NEAR_MISS_THRESHOLD = 0.40

_SYSTEM_PROMPT = """You are a senior engineering career coach with 15 years of experience
helping software professionals map their career growth. Your advice is specific, honest,
and actionable. You reference actual skills, job titles, and timelines — never vague platitudes.
Base your output strictly on the data provided."""


class LearningItem(BaseModel):
    skill: str
    why: str               # which roles / opportunities this unlocks
    estimated_weeks: int   # realistic time to job-ready proficiency
    resources: list[str]   # suggested learning approaches (course names, project ideas)


class TimeHorizon(BaseModel):
    horizon: str           # "now" | "6_months" | "2_years"
    label: str
    roles: list[str]       # job titles realistic for this horizon
    action_items: list[str]


class CareerPathResult(BaseModel):
    current_title: str
    total_exp_years: float
    horizons: list[TimeHorizon]
    learning_roadmap: list[LearningItem]
    summary: str


def generate_career_path(
    candidate_profile: dict,
    scored_jobs: list[dict],
    model_override: str | None = None,
    provider_override: str | None = None,
) -> CareerPathResult:
    """
    Generate a 3-horizon career path and prioritised learning roadmap.

    Args:
        candidate_profile: ParsedResume dict (from resume.parsed_profile)
        scored_jobs:        list of job dicts with match_score, missing_skills, title, company
    """
    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    current_title = candidate_profile.get("current_title", "") or "Software Engineer"
    total_exp = candidate_profile.get("total_experience_years") or 0
    skills = candidate_profile.get("skills") or []
    tools = candidate_profile.get("tools") or []
    summary = candidate_profile.get("summary", "") or ""
    work_history = candidate_profile.get("work_history") or []

    # Segment jobs by score band
    ready_now = [
        j for j in scored_jobs
        if (j.get("match_score") or 0) >= _NOW_THRESHOLD
    ]
    near_miss = [
        j for j in scored_jobs
        if _NEAR_MISS_THRESHOLD <= (j.get("match_score") or 0) < _NOW_THRESHOLD
    ]

    # Aggregate missing skills from near-miss jobs (the most actionable gaps)
    near_miss_gaps: Counter[str] = Counter()
    for j in near_miss:
        for s in (j.get("missing_skills") or []):
            if s:
                near_miss_gaps[s.lower().strip()] += 1

    # Top ready-now titles
    now_titles = list(dict.fromkeys(j.get("title", "") for j in ready_now[:8]))
    # Top near-miss titles
    near_titles = list(dict.fromkeys(j.get("title", "") for j in near_miss[:8]))

    # Top gap skills with frequency
    top_gaps = near_miss_gaps.most_common(12)
    gap_str = "\n".join(f"  - {skill} (missing in {count} near-miss jobs)" for skill, count in top_gaps)

    history_str = "\n".join(
        f"  - {w.get('title','')} @ {w.get('company','')} ({w.get('duration_years',0) or 0:.1f} yrs)"
        for w in work_history[:4]
    ) or "  Not provided"

    user_msg = f"""Build a career path plan for this candidate.

=== CANDIDATE ===
Current Title: {current_title}
Total Experience: {total_exp} years
Summary: {summary[:300]}
Current Skills: {', '.join((skills + tools)[:25])}
Work History:
{history_str}

=== JOB MARKET SIGNALS ===
Roles they can target RIGHT NOW ({len(ready_now)} matches, score ≥ 65%):
{chr(10).join(f'  - {t}' for t in now_titles) or '  None yet'}

Near-miss roles ({len(near_miss)} matches, score 40–65%):
{chr(10).join(f'  - {t}' for t in near_titles) or '  None yet'}

Most frequent skill gaps in near-miss roles:
{gap_str or '  None identified'}

Return a single JSON object:
{{
  "horizons": [
    {{
      "horizon": "now",
      "label": "Ready to apply today",
      "roles": ["3-5 specific job titles they can target now"],
      "action_items": ["3-4 concrete steps to maximise success in these applications right now"]
    }},
    {{
      "horizon": "6_months",
      "label": "6 months from now",
      "roles": ["3-5 job titles reachable after closing key skill gaps"],
      "action_items": ["3-4 specific things to do in the next 6 months"]
    }},
    {{
      "horizon": "2_years",
      "label": "2 year stretch",
      "roles": ["3-5 ambitious but realistic job titles given this trajectory"],
      "action_items": ["3-4 strategic moves over the next 2 years"]
    }}
  ],
  "learning_roadmap": [
    {{
      "skill": "exact skill name",
      "why": "which roles or opportunities this unlocks",
      "estimated_weeks": 6,
      "resources": ["specific course, project, or approach — not just 'take a course'"]
    }}
  ],
  "summary": "3-sentence honest assessment of where this person is, where they're headed, and the single most important thing they should do next"
}}

Rules:
- learning_roadmap must be ordered by impact (highest unlock value first)
- Include 4–6 learning items
- estimated_weeks should be realistic for reaching job-ready proficiency (not mastery)
- resources should name specific platforms (e.g. fast.ai, Andrej Karpathy's course, AWS free tier) where possible
- Roles must match actual job market titles — no invented ones
- Respond with ONLY the JSON object"""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    parsed = _parse_response(response.content.strip())

    horizons = [
        TimeHorizon(
            horizon=h.get("horizon", ""),
            label=h.get("label", ""),
            roles=h.get("roles") or [],
            action_items=h.get("action_items") or [],
        )
        for h in (parsed.get("horizons") or [])
        if isinstance(h, dict)
    ]

    roadmap = [
        LearningItem(
            skill=item.get("skill", ""),
            why=item.get("why", ""),
            estimated_weeks=int(item.get("estimated_weeks", 4)),
            resources=item.get("resources") or [],
        )
        for item in (parsed.get("learning_roadmap") or [])
        if isinstance(item, dict) and item.get("skill")
    ]

    summary = parsed.get("summary", "")
    if not summary:
        summary = (
            f"With {total_exp} years of experience as {current_title}, "
            f"there are {len(ready_now)} roles you can target today. "
            f"Closing gaps in {', '.join(s for s, _ in top_gaps[:3])} "
            "will unlock significantly more opportunities."
        )

    logger.info(
        f"[CareerPath] {current_title} {total_exp}yrs — "
        f"now={len(ready_now)} near_miss={len(near_miss)} roadmap={len(roadmap)}"
    )

    return CareerPathResult(
        current_title=current_title,
        total_exp_years=float(total_exp),
        horizons=horizons,
        learning_roadmap=roadmap,
        summary=summary,
    )


def _parse_response(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[CareerPath] LLM parse error: {e}")
        return {}
