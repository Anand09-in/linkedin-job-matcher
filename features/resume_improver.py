"""
Feature module: resume_improver
Generate specific, actionable resume improvement suggestions tailored to a job description.

Output:
  - overall_fit_grade      A/B/C/D based on current match
  - suggestions[]          per-section issues + concrete rewrites
  - keywords_to_add[]      exact JD keywords missing from resume
  - summary_rewrite        full rewritten Professional Summary for this role
  - top_actions[]          top 3 highest-impact things to do before applying
"""
from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

_SYSTEM_PROMPT = """You are an expert resume writer and ATS optimisation specialist.
You review resumes against specific job descriptions and give concrete, actionable improvements.

Rules:
- Be specific — name exact technologies, provide rewritten bullet points, quote exact phrasing
- Never give vague advice like "improve your summary" without showing EXACTLY how
- Prioritise changes that (a) add missing keywords the ATS will scan and (b) prove impact with numbers
- If a bullet lacks a metric, suggest a plausible quantified version the candidate can verify
- Keep suggestions realistic — don't invent skills the candidate doesn't have"""


class ResumeSuggestion(BaseModel):
    section: str       # Professional Summary | Skills | Work Experience | Achievements | Format
    priority: str      # high | medium | low
    issue: str         # what is wrong or missing
    suggestion: str    # specific action to take
    example: str | None = None   # concrete rewrite example where applicable


class ResumeImprovementResult(BaseModel):
    job_id: str
    job_title: str
    company: str
    overall_fit_grade: str        # A | B | C | D
    suggestions: list[ResumeSuggestion]
    keywords_to_add: list[str]    # exact keywords from JD missing from resume
    summary_rewrite: str          # full rewritten Professional Summary for this role
    top_actions: list[str]        # top 3 highest-impact things to do before applying


def improve_resume(
    job: dict,
    candidate_profile: dict,
    resume_text: str = "",
    model_override: str | None = None,
    provider_override: str | None = None,
) -> ResumeImprovementResult:
    """Generate targeted resume improvement suggestions for a specific job."""
    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    job_id = job.get("id", "")
    job_title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "") or ""
    required_skills = job.get("skills_required") or []
    nice_skills = job.get("skills_nice_to_have") or []
    responsibilities = job.get("responsibilities") or []
    seniority = job.get("seniority_level", "") or "Mid"
    missing_skills = job.get("missing_skills") or []   # already computed by matcher

    name = candidate_profile.get("name", "")
    current_title = candidate_profile.get("current_title", "")
    total_exp = candidate_profile.get("total_experience_years") or 0
    summary = candidate_profile.get("summary", "") or ""
    skills = candidate_profile.get("skills") or []
    tools = candidate_profile.get("tools") or []
    languages = candidate_profile.get("languages") or []
    work_history = candidate_profile.get("work_history") or []

    history_str = "\n".join(
        f"  • {w.get('title','')} @ {w.get('company','')} ({w.get('duration_years',0) or 0:.1f} yrs)"
        + (f"\n    {w.get('description','')[:300]}" if w.get('description') else "")
        for w in work_history[:4]
    ) or "  Not provided"

    resp_str = (
        "\n".join(f"  - {r}" for r in responsibilities[:5])
        if responsibilities else description[:400]
    )

    # Use raw resume text for deeper analysis (first 2500 chars)
    resume_excerpt = resume_text[:2500] if resume_text else "(raw text not available)"

    user_msg = f"""Review this resume against the job description and produce improvement suggestions.

=== TARGET JOB ===
Title: {job_title}
Company: {company}
Seniority: {seniority}
Required Skills: {', '.join(required_skills[:14])}
Nice-to-Have: {', '.join(nice_skills[:8])}
Key Responsibilities:
{resp_str}
Skills already identified as MISSING: {', '.join(missing_skills[:8]) or 'none flagged'}

=== CURRENT RESUME ===
Name: {name or '(not provided)'}
Current Title: {current_title}
Experience: {total_exp} years
Current Summary: {summary[:300] or '(none)'}
Skills: {', '.join(skills[:20])}
Tools/Platforms: {', '.join(tools[:15])}
Languages: {', '.join(languages[:10])}
Work History:
{history_str}

Resume Text Excerpt:
{resume_excerpt}

Return a JSON object (no markdown fences):
{{
  "overall_fit_grade": "A|B|C|D",
  "suggestions": [
    {{
      "section": "Professional Summary|Skills|Work Experience|Achievements|Format",
      "priority": "high|medium|low",
      "issue": "Concise description of the problem",
      "suggestion": "Specific actionable fix",
      "example": "Optional: exact rewritten text or bullet point"
    }}
  ],
  "keywords_to_add": ["keyword1", "keyword2"],
  "summary_rewrite": "A full rewritten Professional Summary (3-4 sentences) tailored to {job_title} at {company}",
  "top_actions": [
    "Action 1 — the single highest-impact change",
    "Action 2",
    "Action 3"
  ]
}}

Rules:
- Provide 4–7 suggestions covering different sections
- keywords_to_add must be EXACT strings from the JD that are missing from the resume
- summary_rewrite must be ready-to-paste (no placeholders)
- top_actions must be specific (e.g. "Add 'MLflow' and 'model registry' to Skills section", not "improve skills")
- overall_fit_grade: A=strong match, B=good with small fixes, C=needs work, D=significant gaps"""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    parsed = _parse_response(response.content.strip())

    suggestions = [
        ResumeSuggestion(
            section=s.get("section", "General"),
            priority=s.get("priority", "medium"),
            issue=s.get("issue", ""),
            suggestion=s.get("suggestion", ""),
            example=s.get("example") or None,
        )
        for s in (parsed.get("suggestions") or [])
        if isinstance(s, dict) and s.get("issue")
    ]

    parse_failed = parsed.get("_parse_failed", False)
    grade = parsed.get("overall_fit_grade", "") or ("?" if parse_failed else "C")

    logger.info(
        f"[ResumeImprover] job={job_id} grade={grade} parse_failed={parse_failed} "
        f"suggestions={len(suggestions)} keywords={len(parsed.get('keywords_to_add') or [])}"
    )
    if parse_failed:
        logger.warning(f"[ResumeImprover] Raw snippet: {parsed.get('_raw','')}")

    return ResumeImprovementResult(
        job_id=job_id,
        job_title=job_title,
        company=company,
        overall_fit_grade=grade,
        suggestions=suggestions,
        keywords_to_add=parsed.get("keywords_to_add") or [],
        summary_rewrite=parsed.get("summary_rewrite", ""),
        top_actions=parsed.get("top_actions") or [],
    )


def _parse_response(raw: str) -> dict:
    # 1. Strip markdown fences
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

    # 2. Try full parse
    try:
        result = json.loads(clean)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 3. Find the outermost {...} block (handles leading/trailing text from chatty models)
    match = re.search(r"\{[\s\S]*\}", clean)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    logger.warning(
        f"[ResumeImprover] Could not parse JSON from LLM response "
        f"(first 200 chars): {raw[:200]}"
    )
    return {"_parse_failed": True, "_raw": raw[:500]}
