"""
Structured-output schemas for the batch extraction+match call (FR-2.1/2.2).

architecture.md §3.3 sketched match_score as a plain `float`; this
implementation makes it `Optional[float]` instead — a deliberate Phase 3
refinement. FR-2.6 pipelines have no resume bound and run "extract-only, no
filter": in that mode there is no meaningful score, and `0.0` would be
indistinguishable from "scored, and it's a bad fit." `None` means "not
scored" unambiguously.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

_MAX_SKILLS = 8


class JobAnalysisResult(BaseModel):
    job_index: int = Field(..., description="0-based position of this job within the batch, for reassembly")

    # Extraction (FR-2.1) — always populated regardless of whether a resume was provided.
    #
    # max_length=8: NOT just a prose instruction in prompts.py — declaring it
    # on the field means it's part of the JSON schema handed to the model as
    # the structured-output tool definition (maxItems), a much stronger
    # signal than prose alone. Confirmed necessary live during Phase 3
    # testing: a prose-only "keep it to ~8" instruction still let Mistral
    # Large spiral into a 280+ item runaway skills_required list (once even
    # degenerating into an unrelated thesaurus of adjectives) for some
    # inputs — the model had no structural signal for when to stop.
    skills_required: list[str] = Field(default_factory=list, max_length=_MAX_SKILLS)
    skills_nice_to_have: list[str] = Field(default_factory=list, max_length=_MAX_SKILLS)
    experience_years_min: Optional[int] = None
    seniority_level: Optional[str] = None
    employment_type: Optional[str] = None
    remote_policy: Optional[str] = None
    education_required: Optional[str] = None
    salary_hint: Optional[str] = None

    # Match assessment (FR-2.2) — None when no resume was provided (FR-2.6).
    match_score: Optional[float] = None
    matched_skills: list[str] = Field(default_factory=list, max_length=_MAX_SKILLS)
    missing_skills: list[str] = Field(default_factory=list, max_length=_MAX_SKILLS)
    match_rationale: Optional[str] = None

    @field_validator(
        "skills_required", "skills_nice_to_have", "matched_skills", "missing_skills", mode="before"
    )
    @classmethod
    def _cap_list_length(cls, value):
        """
        Defensive backstop, not just the schema's max_length declaration
        above: a model can still ignore a maxItems hint entirely (that's
        exactly what happened live — see the field comment). system-design.md
        §3.3's "the LLM scores, the system decides" principle, extended to
        "the LLM proposes a skill list, the system caps it" — truncate rather
        than trust, silently, so one bad batch never turns into a rejected
        run over something this cheap to just fix.
        """
        if isinstance(value, list) and len(value) > _MAX_SKILLS:
            return value[:_MAX_SKILLS]
        return value


class BatchJobAnalysis(BaseModel):
    results: list[JobAnalysisResult]


_MAX_PROFILE_SKILLS = 25


class ResumeProfile(BaseModel):
    """
    A condensed, structured distillation of a resume — parsed by the LLM
    ONCE per resume (parse_resume(), cached in Resume.parsed_profile) and
    reused across every batch call for every pipeline bound to that resume,
    instead of resending the full raw resume text on every single call.

    Raised directly by a real usage question: LLM APIs are stateless per
    call — there's no server-side memory between separate requests, so the
    resume must be IN each request's payload for the model to use it that
    call. What can change is WHAT gets resent: a ~150-300 token structured
    profile instead of the full raw resume text (which can run 1000+
    tokens), computed once and cached rather than recomputed.

    max_length=25, not 8 like a per-job skill list — this is meant to stand
    in for the ENTIRE resume across many different job types in later batch
    calls, so it needs more headroom than "the skills relevant to one job."

    Field ORDER and per-field `description=` matter here, not just cosmetics:
    confirmed live that Mistral Large, given this schema with prose-only
    guidance in the system prompt, dumped the candidate's entire background
    into current_title (the first, shortest field) while leaving
    total_experience_years/skills/summary empty — twice, across two
    different prompt wordings. The fix that actually worked (mirroring the
    max_length lesson: schema constraints bind, prose is advisory) was
    moving the real instructions into each field's own `description=` — part
    of the tool definition the model is filling, not just context around
    it — AND reordering so the naturally verbose fields (summary, skills)
    come BEFORE the short categorical ones (current_title,
    total_experience_years), so there's nowhere earlier in the schema for
    overflow content to spill into.
    """

    summary: str = Field(
        "",
        description=(
            "2-4 plain sentences on the candidate's background, seniority, domain experience, and "
            "strengths — written so a recruiter could judge role fit from this alone, without the "
            "original resume. Only the summary itself, no meta-commentary."
        ),
    )
    skills: list[str] = Field(
        default_factory=list,
        max_length=_MAX_PROFILE_SKILLS,
        description=(
            "Up to 25 of the candidate's most relevant skills/technologies, most prominent/recent "
            "first — not an exhaustive dump of every word that could be a skill."
        ),
    )
    current_title: Optional[str] = Field(
        None,
        description=(
            "Exactly ONE short job title the candidate is presenting themselves as / targeting — e.g. "
            "'Data Engineer' or 'AI/ML Engineer'. If their resume summary brands them with a role that "
            "differs from a generic internal title in their work history (e.g. 'Software Development "
            "Engineer'), use the self-described branding from the summary, not the internal title — "
            "that reflects what they're job-hunting for. A single short string only: no alternatives, "
            "no parenthetical qualifiers, no explanation of your choice, null if genuinely unclear."
        ),
    )
    total_experience_years: Optional[float] = Field(
        None,
        description=(
            "Total years of relevant professional experience as a plain number (fractional is fine, "
            "e.g. 1.5), or null if you can't reasonably estimate it from the text."
        ),
    )

    @field_validator("skills", mode="before")
    @classmethod
    def _cap_skills_length(cls, value):
        """Same defensive backstop as JobAnalysisResult's skill lists — see
        that class's docstring for why a schema max_length alone isn't
        trusted to be enough."""
        if isinstance(value, list) and len(value) > _MAX_PROFILE_SKILLS:
            return value[:_MAX_PROFILE_SKILLS]
        return value


class SalaryBenchmark(BaseModel):
    """
    LLM synthesis of web-search results into a salary estimate (FR-5) — NOT
    LinkedIn data. Location- and experience-aware by construction: the
    search query salary_service.py builds includes the job's location and
    experience level, not just its title, since pay varies materially by
    both (a real usage concern raised directly — a generic national-average
    figure isn't useful for comparison).

    Confirmed live: `currency` defaulting to "USD" and `source_note`
    defaulting to "" caused the model to leave both at their defaults even
    for an India-based search that should have inferred "INR" — the same
    lesson as ResumeProfile (see that class's docstring): a Pydantic default
    becomes a `"default"` key in the JSON schema sent to the model, which
    reads as "this is fine unless told otherwise," not "figure this out."
    Fields that must always be actively reasoned about have NO default here;
    only min_amount/max_amount keep one, since "no figure found" is a
    genuinely valid state for the search to have found nothing.
    """

    source_note: str = Field(
        ...,
        description=(
            "REQUIRED, never empty. One sentence on what informed this estimate — which kind of "
            "sources the search results came from (e.g. 'based on Glassdoor/AmbitionBox listings for "
            "similar roles in Bangalore'). If confidence is low, say plainly why (e.g. 'search results "
            "were sparse/off-topic, this is a rough estimate' or 'no relevant figures were found')."
        ),
    )
    confidence: str = Field(
        ...,
        description="REQUIRED: 'low', 'medium', or 'high' — how reliable this estimate is given the actual search results found, not a generic hedge.",
    )
    currency: str = Field(
        ...,
        description=(
            "REQUIRED: the currency actually used where this job is located, inferred from the job's "
            "location — e.g. 'INR' for a job in India, 'USD' for the United States, 'EUR' for the "
            "Eurozone. Do NOT default to USD for a non-US location."
        ),
    )
    period: str = Field("annual", description="'annual' or 'monthly'.")
    min_amount: Optional[float] = Field(
        None,
        description=(
            "Lower end of the estimated range, or null if no usable figure was found. If you found "
            "only ONE figure (not a range), set both min_amount and max_amount to that same figure — "
            "don't leave one of them null while the other has a value."
        ),
    )
    max_amount: Optional[float] = Field(
        None,
        description="Upper end of the estimated range, or null if no usable figure was found — see min_amount's description for the single-figure case.",
    )


class ReferralContact(BaseModel):
    """One candidate contact surfaced by a PUBLIC web search — never a
    LinkedIn scrape (see referral_service.py's module docstring for why).
    Surfacing only: nothing here initiates any outreach."""

    note: Optional[str] = Field(
        None,
        description="Why this person looks relevant, e.g. 'Software Engineer at Acme Corp, found via public search' — and any staleness caveat.",
    )
    name: str = Field(..., description="The person's name as it appears in the search result.")
    title: Optional[str] = Field(None, description="Their job title/role, if stated in the result.")
    profile_url: Optional[str] = Field(None, description="Their public LinkedIn profile URL, if the result was one.")


class ReferralSearchResult(BaseModel):
    caveat: str = Field(
        "",
        description=(
            "A short disclaimer on data freshness/accuracy: these come from public web search "
            "snippets, not a live LinkedIn lookup, so employment status may be outdated — always "
            "verify on their actual profile before reaching out."
        ),
    )
    contacts: list[ReferralContact] = Field(default_factory=list, max_length=10)

    @field_validator("contacts", mode="before")
    @classmethod
    def _cap_contacts_length(cls, value):
        """Same defensive backstop as the other list fields in this module."""
        if isinstance(value, list) and len(value) > 10:
            return value[:10]
        return value
