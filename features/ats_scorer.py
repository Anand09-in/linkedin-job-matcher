"""
Feature module: ats_scorer
ATS (Applicant Tracking System) scorer — no LLM, runs instantly.

Four scored components:
  1. Keyword density      — whole-word regex match on required skills in resume text
  2. Title word presence  — job title words found in resume
  3. Section detection    — standard resume sections present (Experience, Education, Skills…)
  4. Quantified achievements — numbers / metrics / % in resume (shows impact)

Final score = weighted sum → pass/fail verdict + actionable tips.
"""
from __future__ import annotations

import re
from typing import Optional

from loguru import logger
from pydantic import BaseModel


# ── Component weights ─────────────────────────────────────────────────────────
_W_KEYWORD   = 0.50
_W_TITLE     = 0.20
_W_SECTIONS  = 0.15
_W_QUANT     = 0.15

_SECTION_HEADERS = [
    "experience", "work experience", "employment", "professional experience",
    "education", "academic", "qualifications",
    "skills", "technical skills", "core competencies",
    "summary", "objective", "profile",
    "projects", "certifications", "achievements", "awards",
]

_QUANT_PATTERN = re.compile(
    r"""
    \b\d+[\+%]             # 10+  or  80%
  | \b\d+x\b               # 3x
  | \b\d{1,3}[kKmMbB]\b    # 50k  500M
  | (?:increased|reduced|improved|saved|cut|grew|scaled|delivered)
    \s+(?:by\s+)?\d+       # increased by 40
  | [\$₹£€]\s*\d+          # $50  ₹25
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Stop-words we skip when matching job-title words
_TITLE_STOP = {"senior", "junior", "lead", "staff", "principal", "associate", "mid",
               "engineer", "developer", "manager", "analyst", "specialist", "at", "and",
               "the", "of", "for", "in", "a"}


class ATSComponentScores(BaseModel):
    keyword_density: float          # 0–1
    title_word_presence: float      # 0–1
    section_coverage: float         # 0–1
    quantified_achievements: float  # 0–1  (presence score, not a ratio)


class ATSResult(BaseModel):
    job_id: str
    resume_id: str
    overall_score: float            # 0–100
    components: ATSComponentScores
    matched_keywords: list[str]
    missing_keywords: list[str]
    matched_title_words: list[str]
    missing_title_words: list[str]
    detected_sections: list[str]
    quant_count: int
    predicted_pass: bool
    tips: list[str]


def score_ats(
    job: dict,
    candidate_profile: dict,
    resume_text: str = "",
) -> ATSResult:
    """
    Score the resume against this job's ATS requirements.
    All logic is pure Python — no LLM calls.
    """
    job_id = job.get("id", "")
    resume_id = candidate_profile.get("resume_id", "")
    resume_lower = resume_text.lower() if resume_text else ""

    required_skills = [s.lower().strip() for s in (job.get("skills_required") or [])]
    job_title = (job.get("title", "") or "").lower()

    # ── Component 1: Keyword density (whole-word regex) ───────────────────────
    matched_kw, missing_kw = [], []
    for skill in required_skills:
        pattern = r"\b" + re.escape(skill) + r"\b"
        if re.search(pattern, resume_lower):
            matched_kw.append(skill)
        else:
            missing_kw.append(skill)
    kw_score = len(matched_kw) / len(required_skills) if required_skills else 1.0

    # ── Component 2: Title word presence ─────────────────────────────────────
    title_words = [w for w in re.split(r"\W+", job_title) if w and w not in _TITLE_STOP]
    matched_title, missing_title = [], []
    for w in title_words:
        if re.search(r"\b" + re.escape(w) + r"\b", resume_lower):
            matched_title.append(w)
        else:
            missing_title.append(w)
    title_score = len(matched_title) / len(title_words) if title_words else 1.0

    # ── Component 3: Standard section detection ───────────────────────────────
    detected_sections = []
    for header in _SECTION_HEADERS:
        if re.search(r"\b" + re.escape(header) + r"\b", resume_lower):
            detected_sections.append(header)
    # Score: 4+ unique key sections = 1.0; fewer = proportional
    key_sections = {"experience", "education", "skills", "summary", "projects"}
    key_found = key_sections.intersection(set(detected_sections))
    section_score = min(len(key_found) / 4, 1.0)

    # ── Component 4: Quantified achievements ─────────────────────────────────
    quant_matches = _QUANT_PATTERN.findall(resume_text)
    quant_count = len(quant_matches)
    # Score: 0 = 0.0, 1–2 = 0.5, 3–5 = 0.75, 6+ = 1.0
    if quant_count == 0:
        quant_score = 0.0
    elif quant_count <= 2:
        quant_score = 0.5
    elif quant_count <= 5:
        quant_score = 0.75
    else:
        quant_score = 1.0

    # ── Weighted total ────────────────────────────────────────────────────────
    overall = (
        kw_score    * _W_KEYWORD
        + title_score * _W_TITLE
        + section_score * _W_SECTIONS
        + quant_score * _W_QUANT
    ) * 100

    predicted_pass = overall >= 60.0 and kw_score >= 0.5

    tips = _build_tips(
        missing_kw, missing_title, detected_sections,
        quant_count, overall, kw_score,
    )

    logger.debug(
        f"[ATS] job={job_id} score={overall:.1f} "
        f"kw={kw_score:.0%} title={title_score:.0%} "
        f"sec={section_score:.0%} quant={quant_count} pass={predicted_pass}"
    )

    return ATSResult(
        job_id=job_id,
        resume_id=resume_id,
        overall_score=round(overall, 1),
        components=ATSComponentScores(
            keyword_density=round(kw_score, 3),
            title_word_presence=round(title_score, 3),
            section_coverage=round(section_score, 3),
            quantified_achievements=round(quant_score, 3),
        ),
        matched_keywords=matched_kw,
        missing_keywords=missing_kw,
        matched_title_words=matched_title,
        missing_title_words=missing_title,
        detected_sections=detected_sections,
        quant_count=quant_count,
        predicted_pass=predicted_pass,
        tips=tips,
    )


def _build_tips(
    missing_kw: list[str],
    missing_title: list[str],
    detected_sections: list[str],
    quant_count: int,
    score: float,
    kw_score: float,
) -> list[str]:
    tips: list[str] = []

    if missing_kw:
        tips.append(
            f"Add these exact keywords to your Skills section: {', '.join(missing_kw[:5])}"
        )
    if missing_title:
        tips.append(
            f"Mention these words from the job title in your summary: {', '.join(missing_title)}"
        )

    key_sections = {"experience", "education", "skills", "summary"}
    missing_sections = key_sections - set(detected_sections)
    if missing_sections:
        tips.append(
            f"Your resume may be missing standard sections: {', '.join(missing_sections)}. "
            "ATS parsers rely on these headers."
        )

    if quant_count == 0:
        tips.append(
            "Add quantified achievements (e.g. 'reduced latency by 40%', 'shipped to 1M users') — "
            "metrics improve ATS ranking signals."
        )
    elif quant_count <= 2:
        tips.append(
            f"Only {quant_count} quantified achievement(s) found — add more measurable outcomes to strengthen impact."
        )

    if score < 60:
        tips.append(
            "Overall ATS score below 60 — tailor your resume summary to mirror this job's language before applying."
        )

    if not tips:
        tips.append("Resume looks well-optimised for this role's ATS filters.")

    return tips
