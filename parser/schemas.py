"""
Pydantic v2 schemas for structured LLM output.

These are the contracts between the LLM and the rest of the system.
Every LLM response is validated against these before being stored.

Phase 2.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Job Description parsed output
# ─────────────────────────────────────────────────────────────────────────────

class CompanyInfo(BaseModel):
    size_hint: Optional[str] = None    # startup | mid-size | enterprise
    domain: Optional[str] = None       # fintech | healthtech | ecommerce | etc.


class ParsedJD(BaseModel):
    """
    Structured fields extracted from a raw job description.
    Stored in the Job DB row after Phase 2 enrichment.
    """
    skills_required: list[str] = Field(default_factory=list)
    skills_nice_to_have: list[str] = Field(default_factory=list)
    experience_years: Optional[str] = None          # human-readable e.g. "3-5 years"
    experience_years_min: Optional[int] = None      # integer lower bound for scoring
    seniority_level: Optional[str] = None           # Entry|Junior|Mid|Senior|Lead|Principal
    employment_type: Optional[str] = None           # Full-time|Part-time|Contract
    remote_policy: Optional[str] = None             # Remote|Hybrid|On-site|Flexible
    education_required: Optional[str] = None
    salary_range: Optional[str] = None
    responsibilities: list[str] = Field(default_factory=list)
    company_info: CompanyInfo = Field(default_factory=CompanyInfo)

    @field_validator("skills_required", "skills_nice_to_have", "responsibilities", mode="before")
    @classmethod
    def normalise_list(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return [s.strip().lower() for s in v if isinstance(s, str) and s.strip()]
        return []

    @field_validator("seniority_level", mode="before")
    @classmethod
    def normalise_seniority(cls, v):
        if not v:
            return None
        mapping = {
            "entry": "Entry", "junior": "Junior", "mid": "Mid",
            "senior": "Senior", "lead": "Lead", "principal": "Principal",
            "staff": "Lead", "manager": "Manager", "director": "Director",
        }
        lower = str(v).lower()
        for key, label in mapping.items():
            if key in lower:
                return label
        return str(v).title()

    @field_validator("experience_years_min", mode="before")
    @classmethod
    def coerce_exp_min(cls, v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Resume parsed output
# ─────────────────────────────────────────────────────────────────────────────

class WorkHistoryEntry(BaseModel):
    title: str
    company: str
    duration_years: Optional[float] = None    # e.g. 2.5
    description: Optional[str] = None


class EducationEntry(BaseModel):
    degree: str
    institution: str
    year: Optional[int] = None
    field: Optional[str] = None


class ParsedResume(BaseModel):
    """
    Structured candidate profile extracted from a PDF resume.
    Stored in Resume.parsed_profile as JSON.
    """
    name: Optional[str] = None
    current_title: Optional[str] = None
    total_experience_years: Optional[float] = None
    summary: Optional[str] = None

    skills: list[str] = Field(default_factory=list)       # technical skills
    tools: list[str] = Field(default_factory=list)        # tools / platforms / frameworks
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)    # programming languages

    work_history: list[WorkHistoryEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)

    @field_validator("skills", "tools", "certifications", "languages", mode="before")
    @classmethod
    def normalise_lists(cls, v):
        if isinstance(v, list):
            return [s.strip().lower() for s in v if isinstance(s, str) and s.strip()]
        return []

    @field_validator("total_experience_years", mode="before")
    @classmethod
    def coerce_experience(cls, v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @property
    def all_skills(self) -> list[str]:
        """Union of skills + tools + languages for matching."""
        return list(set(self.skills + self.tools + self.languages))
