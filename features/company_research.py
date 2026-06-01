"""
Feature module: company_research
Mine LinkedIn insights[], JD text, salary hint, and remote policy to surface
culture signals, red/green flags, tech stack hints, and an honest overall impression.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

_SYSTEM_PROMPT = """You are a candid career advisor helping a job seeker evaluate whether
a company is worth pursuing. Give an honest, balanced assessment — not a marketing pitch.
Flag real concerns when you see them. Be specific; avoid vague positives."""


class CompanyResearchResult(BaseModel):
    job_id: str
    company: str
    location: Optional[str]
    # Structured fields mined from LinkedIn insights[]
    seniority_hint: Optional[str]     # from insights[0]
    employment_type: Optional[str]    # from insights[1]
    job_function: Optional[str]       # from insights[2]
    industry: Optional[str]           # from insights[3]
    remote_policy: Optional[str]
    salary_hint: Optional[str]
    # LLM-generated fields
    domain: Optional[str]
    size_hint: Optional[str]
    tech_stack_hints: list[str]
    culture_signals: list[str]
    green_flags: list[str]
    red_flags: list[str]
    overall_impression: str


def research_company(
    job: dict,
    candidate_profile: dict,
    model_override: str | None = None,
    provider_override: str | None = None,
) -> CompanyResearchResult:
    """Analyse company using all available scraped signals + LLM inference."""
    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    job_id = job.get("id", "")
    company = job.get("company", "")
    location = job.get("location", "") or ""
    description = job.get("description", "") or ""
    insights = job.get("insights") or []
    skills_required = job.get("skills_required") or []
    skills_nice = job.get("skills_nice_to_have") or []
    remote_policy = job.get("remote_policy", "") or ""
    salary_hint = job.get("salary_range", "") or ""

    # Mine LinkedIn insights[] array directly
    seniority_hint  = insights[0] if len(insights) > 0 else None
    employment_type = insights[1] if len(insights) > 1 else None
    job_function    = insights[2] if len(insights) > 2 else None
    industry        = insights[3] if len(insights) > 3 else None

    all_skills = list(dict.fromkeys(skills_required + skills_nice))[:20]

    user_msg = f"""Evaluate this employer for a job seeker.

=== STRUCTURED SIGNALS (from LinkedIn) ===
Company: {company}
Location: {location}
Industry: {industry or 'Unknown'}
Job Function: {job_function or 'Unknown'}
Seniority Level: {seniority_hint or 'Unknown'}
Employment Type: {employment_type or 'Unknown'}
Remote Policy: {remote_policy or 'Not stated'}
Salary Range: {salary_hint or 'Not disclosed'}

=== TECH STACK CLUES ===
{', '.join(all_skills) or 'None extracted'}

=== JOB DESCRIPTION ===
{description[:1400]}

Return a single JSON object (no markdown fences):
{{
  "domain": "e.g. fintech|healthtech|saas|ecommerce|enterprise|gaming|consulting",
  "size_hint": "startup|mid-size|enterprise",
  "tech_stack_hints": ["specific technologies inferred from JD language"],
  "culture_signals": ["3-4 observations about work culture inferred from JD wording and company type"],
  "green_flags": ["positive signals worth noting — be specific"],
  "red_flags": ["concerns or warning signs — be honest; empty list if none"],
  "overall_impression": "2-3 sentence honest assessment of what this company and role is likely to be like"
}}"""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    parsed = _parse_response(response.content.strip())

    return CompanyResearchResult(
        job_id=job_id,
        company=company,
        location=location or None,
        seniority_hint=seniority_hint,
        employment_type=employment_type,
        job_function=job_function,
        industry=industry,
        remote_policy=remote_policy or None,
        salary_hint=salary_hint or None,
        domain=parsed.get("domain"),
        size_hint=parsed.get("size_hint"),
        tech_stack_hints=parsed.get("tech_stack_hints") or [],
        culture_signals=parsed.get("culture_signals") or [],
        green_flags=parsed.get("green_flags") or [],
        red_flags=parsed.get("red_flags") or [],
        overall_impression=parsed.get("overall_impression") or (
            f"{company} is a {parsed.get('size_hint','') or ''} "
            f"{parsed.get('domain','technology')} company."
        ),
    )


def _parse_response(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[CompanyResearch] LLM parse error: {e}")
        return {}
