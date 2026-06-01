"""
Feature module: company_intel
Combined company research + salary intelligence in a single LLM call.

1. Web-search DuckDuckGo for real salary data (free, no API key needed).
   Falls back gracefully if duckduckgo-search is not installed.
2. One LLM prompt that handles both company analysis and salary interpretation,
   with the web snippets injected as context so the model can extract real numbers.

Install web search: pip install duckduckgo-search
"""
from __future__ import annotations

import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from features.salary_benchmark import (
    _get_location_info,
    _estimate_band,
    _BENEFITS_TO_ASK,
    _NEGOTIATION_TIPS,
    _SENIORITY_RANGES,
)

_SYSTEM_PROMPT = """You are a candid company research analyst AND a compensation expert.
Given a job description, LinkedIn signals, and web search results about salaries, produce:
1. An honest company assessment (culture, red/green flags, tech stack)
2. A salary estimate backed by the web results

Rules:
- Extract actual salary numbers from the web snippets where possible
- If web snippets mention ranges, use those figures; otherwise estimate from seniority + location
- Be candid about the company — flag real concerns, don't just say positive things
- Respond ONLY with the JSON object requested"""


class WebSnippet(BaseModel):
    title: str
    body: str
    url: str = ""


class CompanyIntelResult(BaseModel):
    job_id: str
    company: str
    location: Optional[str]
    # LinkedIn-sourced metadata
    seniority_hint: Optional[str]
    employment_type: Optional[str]
    job_function: Optional[str]
    industry: Optional[str]
    remote_policy: Optional[str]
    # LLM company analysis
    domain: Optional[str]
    size_hint: Optional[str]
    tech_stack_hints: list[str]
    culture_signals: list[str]
    green_flags: list[str]
    red_flags: list[str]
    overall_impression: str
    # Salary intelligence
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_currency: str = "USD"
    salary_period: str = "annual"
    salary_source: str          # "web" | "jd" | "estimate"
    market_low: float
    market_mid: float
    market_high: float
    your_likely_band: str
    negotiation_tips: list[str]
    benefits_to_ask: list[str]
    # Web search provenance
    web_search_used: bool = False
    search_query: str = ""
    search_snippets: list[WebSnippet] = []


def research_company_with_salary(
    job: dict,
    candidate_profile: dict,
    model_override: str | None = None,
    provider_override: str | None = None,
) -> CompanyIntelResult:
    """
    Combined company + salary analysis.
    Searches the web for salary data first, then calls the LLM once with all context.
    """
    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    job_id       = job.get("id", "")
    company      = job.get("company", "")
    location     = job.get("location", "") or ""
    description  = job.get("description", "") or ""
    insights     = job.get("insights") or []
    skills_req   = job.get("skills_required") or []
    skills_nice  = job.get("skills_nice_to_have") or []
    remote_policy = job.get("remote_policy", "") or ""
    salary_raw    = job.get("salary_range", "") or ""
    seniority     = job.get("seniority_level", "Mid") or "Mid"

    seniority_hint  = insights[0] if len(insights) > 0 else None
    employment_type = insights[1] if len(insights) > 1 else None
    job_function    = insights[2] if len(insights) > 2 else None
    industry        = insights[3] if len(insights) > 3 else None

    job_title = job.get("title", "")
    total_exp = candidate_profile.get("total_experience_years") or 0

    # ── Web search for salary ─────────────────────────────────────────────────
    web_snippets, web_used, search_query, raw_results = _search_salary_web(
        job_title, company, location
    )

    # ── Static market fallback values ─────────────────────────────────────────
    multiplier, currency, fx = _get_location_info(location)
    lo_usd, mid_usd, hi_usd = _SENIORITY_RANGES.get(seniority, _SENIORITY_RANGES["Mid"])
    market_low  = round(lo_usd  * multiplier * fx)
    market_mid  = round(mid_usd * multiplier * fx)
    market_high = round(hi_usd  * multiplier * fx)
    your_band   = _estimate_band(float(total_exp))
    neg_tips    = _NEGOTIATION_TIPS.get(seniority, [
        "Research market rates before negotiating",
        "Never give a number first",
        "Always negotiate — worst they say is no",
    ])

    all_skills = list(dict.fromkeys(skills_req + skills_nice))[:20]

    user_msg = f"""Analyse this company and provide salary intelligence.

=== STRUCTURED JOB SIGNALS (from LinkedIn) ===
Company: {company}
Job Title: {job_title}
Location: {location}
Industry: {industry or 'Unknown'}
Job Function: {job_function or 'Unknown'}
Seniority: {seniority_hint or seniority}
Employment Type: {employment_type or 'Unknown'}
Remote Policy: {remote_policy or 'Not stated'}
Salary (from JD): {salary_raw or 'Not disclosed'}

=== TECH STACK CLUES ===
{', '.join(all_skills) or 'None extracted'}

=== JOB DESCRIPTION ===
{description[:1200]}

=== WEB SALARY SEARCH RESULTS ===
{web_snippets if web_snippets else "No web results available — use market estimates"}

Return a single JSON object (no markdown):
{{
  "domain": "fintech|healthtech|saas|ecommerce|enterprise|consulting|gaming|etc",
  "size_hint": "startup|mid-size|enterprise",
  "tech_stack_hints": ["technologies inferred from JD"],
  "culture_signals": ["3-4 observations about work culture"],
  "green_flags": ["positive signals — be specific"],
  "red_flags": ["concerns or warnings — be honest; empty list if none"],
  "overall_impression": "2-3 sentence honest assessment",
  "salary_min": <number or null — extracted from web/JD, in local currency>,
  "salary_max": <number or null — extracted from web/JD, in local currency>,
  "salary_currency": "{currency}",
  "salary_period": "annual",
  "salary_source": "web|jd|estimate"
}}

For salary: extract real numbers from the web results if available.
If web results mention a range like "12-18 LPA" convert to base units ({currency}).
If no real data, set salary_min/max to null and salary_source to "estimate"."""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    parsed = _parse_response(response.content.strip())

    logger.info(
        f"[CompanyIntel] job={job_id} company={company} "
        f"web_used={web_used} salary_source={parsed.get('salary_source','?')}"
    )

    return CompanyIntelResult(
        job_id=job_id,
        company=company,
        location=location or None,
        seniority_hint=seniority_hint,
        employment_type=employment_type,
        job_function=job_function,
        industry=industry,
        remote_policy=remote_policy or None,
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
        salary_min=parsed.get("salary_min"),
        salary_max=parsed.get("salary_max"),
        salary_currency=parsed.get("salary_currency") or currency,
        salary_period=parsed.get("salary_period", "annual"),
        salary_source=parsed.get("salary_source", "estimate"),
        market_low=market_low,
        market_mid=market_mid,
        market_high=market_high,
        your_likely_band=your_band,
        negotiation_tips=neg_tips,
        benefits_to_ask=_BENEFITS_TO_ASK,
        web_search_used=web_used,
        search_query=search_query,
        search_snippets=[
            WebSnippet(
                title=r.get("title", ""),
                body=r.get("body", ""),
                url=r.get("href", "") or r.get("url", ""),
            )
            for r in raw_results
        ],
    )


# ── Web search helper ─────────────────────────────────────────────────────────

def _search_salary_web(
    job_title: str, company: str, location: str
) -> tuple[str, bool, str, list[dict]]:
    """
    Search DuckDuckGo for salary data.
    Returns (snippets_text, success, query_used, raw_results).
    Requires: pip install ddgs
    """
    loc = location.split(",")[0].strip() if location else ""
    query = f"{job_title} {company} salary {loc} 2024 2025".strip()

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return "", False, query, []
        snippets = "\n".join(
            f"[{r.get('title', '')}]: {r.get('body', '')[:250]}"
            for r in results
        )
        logger.debug(f"[CompanyIntel] Web search '{query}': {len(results)} results")
        return snippets, True, query, results
    except ImportError:
        logger.info("[CompanyIntel] pip install ddgs for live salary data")
        return "", False, query, []
    except Exception as e:
        logger.warning(f"[CompanyIntel] Web search failed: {e}")
        return "", False, query, []


def _parse_response(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    try:
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", clean)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
    logger.warning(f"[CompanyIntel] JSON parse failed, first 200: {raw[:200]}")
    return {}
