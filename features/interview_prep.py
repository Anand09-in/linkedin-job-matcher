"""
Feature module: interview_prep
Generate 12 interview questions (3 per 4 categories) with answer frameworks
and key points. Highly specific to the JD and candidate background.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

_SYSTEM_PROMPT = """You are a senior hiring manager and technical interview coach.
Generate interview questions that are highly specific to the job description and candidate background
provided — never generic. Every question must reference actual skills, technologies, or
responsibilities from the JD. Questions should expose both depth and real-world application."""


class InterviewQuestion(BaseModel):
    category: str            # technical | behavioural | system_design | culture_fit
    question: str
    answer_framework: str    # e.g. "STAR", "3-part", "SOAR", "deep-dive", "opinion-then-evidence"
    key_points: list[str]    # 3–4 specific things to cover in the answer


class InterviewPrepResult(BaseModel):
    job_id: str
    job_title: str
    company: str
    questions: list[InterviewQuestion]
    prep_tips: list[str]


def generate_interview_prep(
    job: dict,
    candidate_profile: dict,
    model_override: str | None = None,
    provider_override: str | None = None,
) -> InterviewPrepResult:
    """Generate 12 tailored interview questions across 4 categories."""
    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    job_title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "") or ""
    required_skills = job.get("skills_required") or []
    missing_skills = job.get("missing_skills") or []
    matched_skills = job.get("matched_skills") or []
    seniority = job.get("seniority_level", "") or "Mid"
    responsibilities = job.get("responsibilities") or []

    current_title = candidate_profile.get("current_title", "")
    total_exp = candidate_profile.get("total_experience_years") or 0
    work_history = candidate_profile.get("work_history") or []

    history_str = "\n".join(
        f"- {w.get('title','')} @ {w.get('company','')} ({w.get('duration_years',0) or 0:.1f} yrs)"
        for w in work_history[:3]
    ) or "Not provided"

    resp_str = "\n".join(f"- {r}" for r in responsibilities[:5]) if responsibilities else description[:400]

    user_msg = f"""Generate exactly 12 interview questions for this candidate + role.

=== JOB ===
Title: {job_title}
Company: {company}
Seniority: {seniority}
Required Skills: {', '.join(required_skills[:14])}
Key Responsibilities:
{resp_str}
Description excerpt: {description[:500]}

=== CANDIDATE ===
Current Title: {current_title}
Experience: {total_exp} years
Matched Skills: {', '.join(matched_skills[:10])}
Skill Gaps: {', '.join(missing_skills[:6]) or 'none identified'}
Work History:
{history_str}

Return a JSON array of exactly 12 objects — 3 per category in this order:
  technical, behavioural, system_design, culture_fit

Schema for each object:
{{
  "category": "technical|behavioural|system_design|culture_fit",
  "question": "The full interview question — highly specific to this role and JD",
  "answer_framework": "STAR|3-part|SOAR|deep-dive|opinion-then-evidence",
  "key_points": ["point 1", "point 2", "point 3"]
}}

Rules:
- technical: reference actual technologies from the JD (e.g., specific framework/tool names)
- behavioural: reference actual responsibilities or scenarios from this role
- system_design: scale/architecture problems relevant to {company}'s likely use case
- culture_fit: probe for alignment with signals in the JD language and company type
- key_points must be actionable — what should the candidate specifically say?
- Calibrate complexity to {seniority} level

Respond with ONLY the JSON array."""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    questions = _parse_questions(response.content.strip())
    prep_tips = _build_prep_tips(job, candidate_profile)

    return InterviewPrepResult(
        job_id=job.get("id", ""),
        job_title=job_title,
        company=company,
        questions=questions,
        prep_tips=prep_tips,
    )


def _parse_questions(raw: str) -> list[InterviewQuestion]:
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        items = json.loads(clean)
        return [
            InterviewQuestion(
                category=item.get("category", "general"),
                question=item.get("question", ""),
                answer_framework=item.get("answer_framework", "STAR"),
                key_points=item.get("key_points") or [],
            )
            for item in items
            if isinstance(item, dict) and item.get("question")
        ]
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[InterviewPrep] LLM parse error: {e}")
        return [
            InterviewQuestion(
                category="general",
                question="Walk me through your most relevant project for this role.",
                answer_framework="STAR",
                key_points=[
                    "State the business problem, not just the technical one",
                    "Describe your specific contribution vs. the team's",
                    "Quantify the outcome where possible",
                ],
            )
        ]


def _build_prep_tips(job: dict, candidate_profile: dict) -> list[str]:
    company = job.get("company", "the company")
    missing = job.get("missing_skills") or []
    seniority = job.get("seniority_level", "") or ""

    tips = [
        f"Research {company}'s engineering blog, recent funding news, and key products before the interview",
        "For every STAR story, practise delivering it in under 2 minutes — time yourself",
    ]
    if missing:
        tips.append(
            f"Skill gaps flagged ({', '.join(missing[:3])}) — frame these as 'actively learning' "
            "with a concrete example of fast skill acquisition from your history"
        )
    if seniority in ("Senior", "Lead", "Principal", "Manager", "Director"):
        tips.append(
            "Prepare a system design story: a decision you made, the trade-offs you weighed, "
            "and the outcome — interviewers at this level probe for ownership"
        )
    tips.append(
        "Prepare 4–5 thoughtful questions for the interviewer covering: team structure, "
        "on-call culture, tech debt appetite, and growth path"
    )
    return tips
