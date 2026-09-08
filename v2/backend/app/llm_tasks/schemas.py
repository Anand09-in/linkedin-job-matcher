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

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field, field_validator

_MAX_SKILLS = 8


@dataclass
class JobContext:
    """Plain data carrier for what a Phase 6 feature prompt needs about a
    Job row — assembled by services/feature_service.py from the ORM row so
    prompts.py (llm_tasks layer) never depends on app.domain directly."""

    title: str
    company: str
    location: Optional[str] = None
    seniority_level: Optional[str] = None
    employment_type: Optional[str] = None
    remote_policy: Optional[str] = None
    description: Optional[str] = None
    skills_required: list[str] = field(default_factory=list)
    skills_nice_to_have: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    salary_benchmark: Optional[dict] = None


@dataclass
class ResumeContext:
    """Plain data carrier combining a resume's cached ResumeProfile with its
    raw text (only resume_improvement.py needs the raw text, for a deeper
    excerpt than the condensed profile provides)."""

    current_title: Optional[str] = None
    total_experience_years: Optional[float] = None
    skills: list[str] = field(default_factory=list)
    summary: Optional[str] = None
    raw_text: str = ""


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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6 — on-demand features (FR-6). Each schema below is deliberately just
# the LLM-authored content: derived/echo fields (word counts, which contact
# was addressed, timestamps, cache flags) are assembled by
# services/feature_service.py afterward, not asked of the model — mirroring
# how job_index above is model-filled bookkeeping but word counts etc. in
# earlier features were always computed in code, never trusted to the model.
#
# Every field that requires the model to actually reason about THIS job/
# resume (not a placeholder-safe default) is declared `Field(...)` with no
# default, per the lesson repeated three times already in Phase 3/4 (see
# ResumeProfile's and SalaryBenchmark's docstrings): a Pydantic default shows
# up as a `"default"` key in the structured-output schema, which models read
# as "fine to leave as-is," not "must fill in." Every list field caps length
# via `max_length` (schema-level, a stronger signal than prose) AND a
# defensive `@field_validator` backstop, since a model can still ignore a
# maxItems hint under some inputs (also observed directly in Phase 3).
# ─────────────────────────────────────────────────────────────────────────────

_MAX_FEATURE_LIST = 10


class CoverLetterResult(BaseModel):
    cover_letter: str = Field(
        ...,
        description=(
            "REQUIRED. A complete cover letter in real letter format, ready to paste as-is, with THREE "
            "required structural pieces in this exact order and never omitted: (1) the line 'Dear "
            "Hiring Manager,' (or a named contact if one is given) as its own opening line, (2) exactly "
            "3 body paragraphs, (3) the word 'Sincerely,' alone on its own final line — this closing "
            "line is REQUIRED, never leave the letter without it. No address block, date, or subject "
            "line, and no name after 'Sincerely,' (the candidate's name isn't given to you, so never "
            "invent a placeholder like '[Your Name]'). The 3 body paragraphs: (1) a hook "
            "referencing something concrete and specific about this exact role/company from the job "
            "description, (2) how the candidate's ACTUAL background (from the resume material given) "
            "connects to a stated requirement — use a specific, real achievement ONLY if the raw resume "
            "excerpt actually contains one with real detail; otherwise speak honestly and specifically "
            "about their real skills/experience without inventing a metric or story that isn't in the "
            "resume text, (3) a one-sentence close on why this role is the logical next step plus a "
            "one-sentence call to action. Target length is given in the prompt — treat it as the target "
            "for the 3 body paragraphs combined. Never use cliché phrases like 'excited to apply', "
            "'passionate about', 'team player', 'results-driven', 'hard worker', 'think outside the "
            "box', or open the first body paragraph with the word 'I'."
        ),
    )


class InterviewQuestion(BaseModel):
    category: str = Field(
        ...,
        description="REQUIRED: exactly one of 'technical', 'behavioural', 'system_design', or 'culture_fit'.",
    )
    question: str = Field(
        ...,
        description=(
            "The full interview question — highly specific to THIS job's actual tech stack/"
            "responsibilities from its description, never generic boilerplate."
        ),
    )
    answer_framework: str = Field(
        ...,
        description="How to structure the answer, e.g. 'STAR', '3-part', 'SOAR', 'deep-dive', or 'opinion-then-evidence'.",
    )
    key_points: list[str] = Field(
        default_factory=list,
        max_length=4,
        description="3-4 specific, actionable things the candidate should actually say in their answer.",
    )

    @field_validator("key_points", mode="before")
    @classmethod
    def _cap_key_points(cls, value):
        if isinstance(value, list) and len(value) > 4:
            return value[:4]
        return value


class InterviewPrepResult(BaseModel):
    questions: list[InterviewQuestion] = Field(
        ...,
        max_length=12,
        description=(
            "Exactly 12 questions in this order: 3 technical, 3 behavioural, 3 system_design, 3 "
            "culture_fit — technical ones must reference actual technologies named in the JD; "
            "system_design ones should be scale/architecture problems relevant to this company's "
            "likely use case; complexity calibrated to the job's seniority level."
        ),
    )
    prep_tips: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "4-5 concrete prep tips specific to this company/role/candidate — e.g. how to frame a "
            "flagged skill gap, what to research beforehand — never generic advice like 'be yourself'."
        ),
    )

    @field_validator("questions", mode="before")
    @classmethod
    def _sanitize_questions(cls, value):
        """
        Defensive backstop, not just the schema's max_length declaration
        above: confirmed live that Mistral Large generating this 12-item
        list of richly detailed objects can truncate mid-item under a
        single-feature token budget, leaving a dict like
        {"category": "system_design"} with `question`/`answer_framework`
        missing — see config.llm_interview_prep_max_tokens's docstring for
        the token-budget fix. Without this, Pydantic raises on that one
        malformed item and crashes the ENTIRE feature call. Same "the LLM
        proposes, the system decides" principle as the skill-list caps
        elsewhere in this module — drop only the malformed items rather
        than fail the whole request over one incomplete one.
        """
        if not isinstance(value, list):
            return value
        cleaned = [
            item
            for item in value
            if not isinstance(item, dict) or (item.get("question") and item.get("answer_framework"))
        ]
        return cleaned[:12]

    @field_validator("prep_tips", mode="before")
    @classmethod
    def _cap_prep_tips(cls, value):
        if isinstance(value, list) and len(value) > 5:
            return value[:5]
        return value


class CompanyResearchResult(BaseModel):
    domain: Optional[str] = Field(
        None, description="Industry domain, e.g. fintech, healthtech, saas, ecommerce, enterprise, gaming, consulting."
    )
    size_hint: Optional[str] = Field(None, description="'startup', 'mid-size', or 'enterprise', inferred from the posting/company signals.")
    tech_stack_hints: list[str] = Field(
        default_factory=list, max_length=_MAX_FEATURE_LIST,
        description="Specific technologies/tools inferred from the job description's actual wording.",
    )
    culture_signals: list[str] = Field(
        default_factory=list, max_length=5,
        description="3-5 specific observations about work culture inferred from the JD's wording and company type.",
    )
    green_flags: list[str] = Field(
        default_factory=list, max_length=5, description="Specific positive signals worth noting — empty list if genuinely none stand out."
    )
    red_flags: list[str] = Field(
        default_factory=list, max_length=5,
        description="Specific concerns or warning signs — be honest; empty list if none, never invent one just to seem balanced.",
    )
    overall_impression: str = Field(
        ...,
        description=(
            "REQUIRED, never generic: 2-3 sentence honest, candid assessment of what this company and "
            "role is likely to be like for THIS candidate — not a marketing pitch."
        ),
    )

    @field_validator("tech_stack_hints", "culture_signals", "green_flags", "red_flags", mode="before")
    @classmethod
    def _cap_lists(cls, value):
        if isinstance(value, list) and len(value) > _MAX_FEATURE_LIST:
            return value[:_MAX_FEATURE_LIST]
        return value


class ResumeSuggestion(BaseModel):
    section: str = Field(
        ..., description="Which resume section this applies to: 'Professional Summary', 'Skills', 'Work Experience', 'Achievements', or 'Format'."
    )
    priority: str = Field(..., description="REQUIRED: 'high', 'medium', or 'low'.")
    issue: str = Field(..., description="What's specifically wrong or missing, relative to THIS job's requirements.")
    suggestion: str = Field(..., description="The specific, actionable fix — never vague advice like 'improve your summary'.")
    example: Optional[str] = Field(None, description="A concrete rewritten example (a bullet point or phrase), where applicable.")


class ResumeImprovementResult(BaseModel):
    overall_fit_grade: str = Field(
        ...,
        description=(
            "REQUIRED, your own honest judgment call — not a placeholder: 'A' (strong match), 'B' "
            "(good, small fixes needed), 'C' (needs real work), or 'D' (significant gaps)."
        ),
    )
    suggestions: list[ResumeSuggestion] = Field(
        default_factory=list, max_length=7, description="4-7 suggestions covering different resume sections, ordered by priority."
    )
    keywords_to_add: list[str] = Field(
        default_factory=list, max_length=_MAX_FEATURE_LIST,
        description="Exact keyword strings taken from the job description that are missing from the candidate's current skill list.",
    )
    summary_rewrite: str = Field(
        ...,
        description=(
            "REQUIRED, ready-to-paste: a full rewritten Professional Summary (3-4 sentences) tailored "
            "specifically to this exact job title and company — no placeholders."
        ),
    )
    top_actions: list[str] = Field(
        default_factory=list, max_length=3,
        description="The 1-3 highest-impact, specific actions to take before applying — e.g. exact skill/keyword to add, never vague.",
    )

    @field_validator("suggestions", mode="before")
    @classmethod
    def _cap_suggestions(cls, value):
        if isinstance(value, list) and len(value) > 7:
            return value[:7]
        return value

    @field_validator("keywords_to_add", mode="before")
    @classmethod
    def _cap_keywords(cls, value):
        if isinstance(value, list) and len(value) > _MAX_FEATURE_LIST:
            return value[:_MAX_FEATURE_LIST]
        return value

    @field_validator("top_actions", mode="before")
    @classmethod
    def _cap_top_actions(cls, value):
        if isinstance(value, list) and len(value) > 3:
            return value[:3]
        return value


class AllFeaturesResult(BaseModel):
    """One combined structured-output call replacing four separate ones —
    added per explicit user request: opening a job's on-demand features
    should cost one LLM call for cover_letter/interview_prep/
    company_research/resume_improvement, not four independent round trips.
    referral_message (needs contact-info params the user hasn't supplied
    yet at that point) and referral_search (needs a live web search's
    results fed in first, not just job/resume context) stay separate,
    on-demand-only calls — bundling those wouldn't make sense the way
    these four "generate straight from job+resume" tasks do.

    Nesting doesn't lose each field's own instructions: the full nested
    JSON schema (every description= on every class above) still reaches
    the model as part of the structured-output tool definition, exactly as
    if each were requested standalone."""

    cover_letter: CoverLetterResult
    interview_prep: InterviewPrepResult
    company_research: CompanyResearchResult
    resume_improvement: ResumeImprovementResult


class ReferralMessageResult(BaseModel):
    """A single field on purpose: channel/contact name/tone are caller-
    supplied context baked into the prompt (referral_message.py), not
    something the model needs to classify or restate — one less place for
    the model to drift from what was actually asked for."""

    message: str = Field(
        ...,
        description=(
            "REQUIRED. The complete outreach message text, ready to send as-is — personalized using "
            "the specific contact name/title and job/company context given in the prompt, concise, no "
            "generic filler, no unfilled placeholders like '[Name]', and respecting whatever "
            "length/tone constraint the prompt specifies for the target channel. The sender's own name "
            "is NOT given to you, so if the message closes with a sign-off (a DM/InMail can; a "
            "connection request should not, it has no room), end it with just 'Best,' or 'Thanks,' and "
            "STOP THERE — never invent or leave a placeholder like '[Your Name]' after it; LinkedIn "
            "already shows the sender's real name/photo next to the message, so no signature is needed."
        ),
    )


