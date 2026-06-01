"""
Feature module: cover_letter
Tailored cover letter generation with cliché-free system prompt.
Results cached in-memory per (job_id, tone) so re-renders don't re-spend tokens.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

# In-memory cache: "{job_id}:{tone}" → CoverLetterResult
_CACHE: dict[str, "CoverLetterResult"] = {}

_SYSTEM_PROMPT = """You are a career coach who writes sharp, memorable cover letters.

RULES — follow every one without exception:
- NEVER use: "excited to apply", "passionate about", "motivated individual", "team player",
  "results-driven", "hard worker", "go-getter", "think outside the box", "leverage my skills",
  "I am writing to apply", "I would be a great fit", "dedicated professional"
- Do NOT open the letter with the word "I"
- Write exactly 3 paragraphs — no more, no less
- Paragraph 1 — The Hook: Reference something concrete and specific about the company or
  this exact role (their product, a specific tech requirement from the JD, a known engineering
  challenge). Show you read the posting carefully. 2–3 sentences max.
- Paragraph 2 — The Evidence: One strong, specific achievement from the candidate's actual
  work history. Use the real company name and role title. Include a concrete outcome where
  possible. Tie it directly to a stated requirement.
- Paragraph 3 — The Close: One sentence on why this role is the logical next step for the
  candidate. One-sentence call to action. Stop there.
- Match the requested tone: professional = formal but human; confident = assertive, no hedging;
  friendly = warm but still sharp
- Body text only — no address, date, subject line, or "Sincerely"."""


class CoverLetterResult(BaseModel):
    job_id: str
    job_title: str
    company: str
    cover_letter: str
    tone: str = "professional"
    word_count: int = 0
    cached: bool = False


def generate_cover_letter(
    job: dict,
    candidate_profile: dict,
    tone: str = "professional",
    model_override: str | None = None,
    provider_override: str | None = None,
) -> CoverLetterResult:
    """
    Generate a tailored 3-paragraph cover letter.
    Returns a cached result if this (job_id, tone) pair was already generated.
    """
    job_id = job.get("id", "")
    cache_key = f"{job_id}:{tone}"

    if cache_key in _CACHE:
        logger.debug(f"[CoverLetter] cache hit job={job_id} tone={tone}")
        cached = _CACHE[cache_key].model_copy()
        cached.cached = True
        return cached

    from config.llm_factory import get_llm
    llm = get_llm(provider=provider_override, model=model_override)

    job_title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "") or ""
    skills_required = job.get("skills_required") or []
    responsibilities = job.get("responsibilities") or []
    matched_skills = job.get("matched_skills") or []

    name = candidate_profile.get("name", "")
    current_title = candidate_profile.get("current_title", "")
    total_exp = candidate_profile.get("total_experience_years") or 0
    summary = candidate_profile.get("summary", "") or ""
    skills = candidate_profile.get("skills") or []
    work_history = candidate_profile.get("work_history") or []

    history_lines = []
    for w in work_history[:4]:
        title = w.get("title", "")
        co = w.get("company", "")
        yrs = w.get("duration_years") or 0
        desc = w.get("description", "") or ""
        history_lines.append(
            f"- {title} @ {co} ({float(yrs):.1f} yrs)"
            + (f": {desc[:200]}" if desc else "")
        )
    history_str = "\n".join(history_lines) or "Not provided"

    responsibilities_str = (
        "\n".join(f"- {r}" for r in responsibilities[:6])
        if responsibilities
        else description[:600]
    )

    user_msg = f"""Write a {tone} cover letter for this application.

=== JOB ===
Title: {job_title}
Company: {company}
Required Skills: {', '.join(skills_required[:12])}
Key Responsibilities:
{responsibilities_str}

=== CANDIDATE ===
Name: {name or '(not provided)'}
Current Title: {current_title}
Total Experience: {total_exp} years
Summary: {summary[:300]}
Technical Skills: {', '.join(skills[:18])}
Skills that match this role: {', '.join(matched_skills[:8])}
Recent Work History:
{history_str}

Write the 3-paragraph letter body now. Nothing before or after it."""

    response = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])
    letter = response.content.strip()

    result = CoverLetterResult(
        job_id=job_id,
        job_title=job_title,
        company=company,
        cover_letter=letter,
        tone=tone,
        word_count=len(letter.split()),
        cached=False,
    )
    _CACHE[cache_key] = result
    logger.info(f"[CoverLetter] generated job={job_id} tone={tone} words={result.word_count}")
    return result


def clear_cache(job_id: str | None = None) -> None:
    """Clear in-memory cache. Pass job_id to clear only one job."""
    if job_id is None:
        _CACHE.clear()
    else:
        for k in [k for k in _CACHE if k.startswith(f"{job_id}:")]:
            del _CACHE[k]
