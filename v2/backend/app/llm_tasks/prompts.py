"""Prompt construction for the batch extraction+match call (FR-2.1/2.2) and
the one-time resume-parsing call (see resume_parser.py)."""
from __future__ import annotations

from app.llm_tasks.schemas import JobContext, ResumeContext, ResumeProfile
from app.scrapers.base import RawJob

RESUME_PARSE_SYSTEM_PROMPT = """You are an expert technical recruiter.

Read the resume below and fill in the requested candidate profile — each
field's own description tells you exactly what belongs in it. This profile
will be reused AS-IS to assess this candidate's fit against many different
job postings later, without the original resume text being shown again — so
it must stand on its own.

Fill in every field with ONLY its answer — no meta-commentary, no hedging
between options, no explaining your reasoning, no alternatives. If you're
torn between two possible values for a field, silently pick the single best
one.
"""


def build_resume_parse_prompt(raw_text: str) -> str:
    return raw_text

SYSTEM_PROMPT = """You are an expert technical recruiter and resume screener.

You will be given a candidate profile (a condensed distillation of their
resume, already extracted — or a note that none was provided) and a batch of
job postings. For EVERY job posting, in order, extract structured
information from its description and — only if a profile was provided —
assess how well the candidate matches it.

Rules:
- Always return exactly one result per job, using its 0-based position in
  the batch as job_index. Process jobs in the order given.
- skills_required / skills_nice_to_have: at most 8 short skill or technology
  names per list (e.g. "Python", "AWS", "Kubernetes"), not full sentences and
  not a paraphrase of the job description. List only skills/technologies
  EXPLICITLY named in the posting text — do not brainstorm related or
  implied technologies that aren't actually written there. If more than 8
  are named, keep the 8 most important ones. Nice-to-have means explicitly
  optional/preferred in the text; everything else explicitly required goes
  in skills_required.
- experience_years_min: the MINIMUM years of experience, ALWAYS normalized to
  a plain integer regardless of how the posting phrases it, so results can be
  filtered and sorted consistently. Postings phrase this many different ways
  — normalize all of them using the LOWER bound / floor of what's stated:
    "1+ years"              -> 1
    "0-2 years"             -> 0
    "3-5 years"             -> 3
    "minimum 2 yrs"         -> 2
    "at least 4 years"      -> 4
    "5 years or more"       -> 5
    "fresher" / "entry level" / "no experience required" / "0-1 years" -> 0
  If truly no experience signal is stated anywhere in the text, use null —
  never guess a number that isn't grounded in the text.
- seniority_level: one of "Entry", "Junior", "Mid", "Senior", "Lead",
  "Principal", or null if unclear from the text.
- employment_type: one of "Full-time", "Part-time", "Contract",
  "Internship", or null if unclear.
- remote_policy: one of "Remote", "Hybrid", "On-site", or null if unclear.
- education_required: a short phrase (e.g. "Bachelor's in CS") or null.
- salary_hint: any compensation figure mentioned, verbatim, or null.
- If the candidate profile section below says none was provided: set
  match_score to null, matched_skills and missing_skills to empty lists, and
  match_rationale to null. Do not guess a score.
- If a profile WAS provided: match_score is your honest 0.0-1.0 assessment of
  OVERALL fit — reason about it the way an experienced recruiter would, not
  a keyword search. Specifically:
    - Recognize equivalent/transferable skills even when the exact word
      differs from the posting (e.g. profile lists "PyTorch", posting asks
      for "deep learning frameworks" — that counts as a match; "REST APIs"
      and "API development" are the same skill stated differently; a
      candidate with "TensorFlow" listed is a reasonable partial match for a
      "PyTorch" requirement, not a hard miss, since the underlying skill —
      building/training neural networks — transfers).
      Weigh how central the missing exact skill is to the role, not just
      whether the literal string appears in the profile's skill list.
    - Use the profile's summary to judge overall trajectory and depth, not
      only its skill list as a checklist: someone with strong, closely
      related experience can be a good match even if a specific named tool
      is absent from or listed less prominently in their profile than the
      posting emphasizes it.
    - matched_skills is the subset of skills_required the candidate
      genuinely has (per their profile) or has a clear equivalent/
      transferable skill for; missing_skills is the subset with no
      reasonable equivalent. match_rationale is exactly one concise sentence
      explaining the score — if you counted an equivalent skill as a match,
      say so briefly.
"""


def build_batch_prompt(jobs: list[RawJob], resume_profile: ResumeProfile | None) -> str:
    if resume_profile is None:
        profile_section = "CANDIDATE PROFILE: none provided — extract only, do not attempt matching.\n"
    else:
        profile_section = (
            "CANDIDATE PROFILE (pre-extracted from their resume):\n"
            f"Current title: {resume_profile.current_title or 'unknown'}\n"
            f"Total experience: "
            f"{resume_profile.total_experience_years if resume_profile.total_experience_years is not None else 'unknown'} years\n"
            f"Skills: {', '.join(resume_profile.skills) or 'none listed'}\n"
            f"Summary: {resume_profile.summary or 'none provided'}\n"
        )

    job_sections = [
        f"--- JOB {i} ---\nTitle: {job.title}\nCompany: {job.company}\nDescription:\n{job.description}\n"
        for i, job in enumerate(jobs)
    ]

    return profile_section + "\n" + "\n".join(job_sections)


# ── Salary synthesis (FR-5) ───────────────────────────────────────────────────

SALARY_SYNTHESIS_SYSTEM_PROMPT = """You are a compensation research analyst.

You will be given a job (title, company, location, seniority/experience
level) and a set of web search result snippets about salaries for similar
roles. Synthesize them into a salary estimate — each field's own description
tells you exactly what belongs in it.

Base your estimate ONLY on what the search results actually say. If the
results are sparse, off-topic, or don't mention real figures, say so plainly
in source_note and set confidence to "low" and the amounts to null — do not
invent a plausible-sounding number with no basis in the results. Location
and seniority matter: a figure for a different city or a clearly different
seniority level than the job in question is weak evidence, not a
direct answer — reflect that in confidence, not by silently ignoring it.
"""


def build_salary_synthesis_prompt(
    job_title: str, company: str, location: str | None, experience_years_min: int | None, search_results_text: str
) -> str:
    return (
        f"JOB: {job_title} at {company}\n"
        f"Location: {location or 'unknown'}\n"
        f"Experience level: {experience_years_min if experience_years_min is not None else 'unknown'} years minimum\n\n"
        f"SEARCH RESULTS:\n{search_results_text or '(no results found)'}\n"
    )


# ── Referral contact search (on-demand, web-search-only — see
#    referral_service.py's module docstring for why this is NOT a LinkedIn
#    scrape) ────────────────────────────────────────────────────────────────

REFERRAL_SYNTHESIS_SYSTEM_PROMPT = """You are helping a job seeker find people
to ask for a referral at a specific company.

You will be given a target company/role and a set of public web search
result snippets (from searching for public LinkedIn profiles and similar
public pages). Extract real people who plausibly work or worked at that
company from these snippets — each field's own description tells you what
belongs in it.

Rules:
- Only include people who are ACTUALLY named in the search results, with
  a real profile URL from the results — never invent a plausible-sounding
  name or guess someone might exist. If no real people are found in the
  results, return an empty contacts list — do not fabricate to look useful.
- Prefer results that look like current employees (title mentions the
  company, or the result is clearly a profile page for that company) over
  ambiguous ones.
- This is a snapshot from a public search, not a live lookup — always
  reflect that these could be outdated in the caveat field.
"""


def build_referral_synthesis_prompt(company: str, job_title: str, search_results_text: str) -> str:
    return (
        f"TARGET COMPANY: {company}\n"
        f"ROLE OF INTEREST: {job_title}\n\n"
        f"SEARCH RESULTS:\n{search_results_text or '(no results found)'}\n"
    )


# ── Phase 6 — on-demand features (FR-6). Each takes a JobContext/
#    ResumeContext pair built by feature_service.py from the DB, so a
#    prompt-builder here never sees a SQLAlchemy row directly. ─────────────

def _job_block(job: JobContext) -> str:
    return (
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Location: {job.location or 'unknown'}\n"
        f"Seniority: {job.seniority_level or 'unknown'}\n"
        f"Employment type: {job.employment_type or 'unknown'}\n"
        f"Remote policy: {job.remote_policy or 'unknown'}\n"
        f"Required skills: {', '.join(job.skills_required) or 'none extracted'}\n"
        f"Nice-to-have skills: {', '.join(job.skills_nice_to_have) or 'none extracted'}\n"
        f"Description:\n{(job.description or '')[:1500]}\n"
    )


def _resume_block(resume: ResumeContext) -> str:
    return (
        f"Current title: {resume.current_title or 'unknown'}\n"
        f"Total experience: {resume.total_experience_years if resume.total_experience_years is not None else 'unknown'} years\n"
        f"Skills: {', '.join(resume.skills) or 'none listed'}\n"
        f"Summary: {resume.summary or 'none provided'}\n"
    )


COVER_LETTER_SYSTEM_PROMPT = """You are a career coach who writes sharp, memorable cover letters
that never read like a template. Follow the cover_letter field's own description exactly — it is
the full spec for structure, length, and banned phrases."""


def build_cover_letter_prompt(job: JobContext, resume: ResumeContext, tone: str) -> str:
    return (
        f"Write a {tone} cover letter for this application.\n\n"
        f"=== JOB ===\n{_job_block(job)}\n"
        f"Skills this candidate already matches on this job: {', '.join(job.matched_skills) or 'none recorded'}\n\n"
        f"=== CANDIDATE ===\n{_resume_block(resume)}"
    )


INTERVIEW_PREP_SYSTEM_PROMPT = """You are a senior hiring manager and technical interview coach.
Generate interview questions highly specific to the job description and candidate background given —
never generic. Every technical/system_design question must reference actual technologies or
responsibilities from the JD."""


def build_interview_prep_prompt(job: JobContext, resume: ResumeContext) -> str:
    return (
        f"=== JOB ===\n{_job_block(job)}\n"
        f"=== CANDIDATE ===\n{_resume_block(resume)}\n"
        f"Skills this candidate matches on this job: {', '.join(job.matched_skills) or 'none recorded'}\n"
        f"Skill gaps flagged for this job: {', '.join(job.missing_skills) or 'none flagged'}\n"
    )


COMPANY_RESEARCH_SYSTEM_PROMPT = """You are a candid career advisor helping a job seeker evaluate
whether a company/role is worth pursuing. Give an honest, balanced assessment, not a marketing
pitch — flag real concerns when the JD's own wording suggests them. Be specific; avoid vague
positives like "great culture" with nothing backing it."""


def build_company_research_prompt(job: JobContext) -> str:
    return f"=== JOB ===\n{_job_block(job)}"


RESUME_IMPROVEMENT_SYSTEM_PROMPT = """You are an expert resume writer and ATS-optimisation
specialist. Review a resume against one specific job description and give concrete, actionable
improvements.

Rules:
- Be specific — name exact technologies, provide rewritten bullet points, quote exact phrasing.
- Never give vague advice like "improve your summary" without showing EXACTLY how.
- Prioritise changes that (a) add missing keywords an ATS will scan for and (b) prove impact with
  numbers.
- Keep suggestions realistic — don't invent skills the candidate doesn't have."""


def build_resume_improvement_prompt(job: JobContext, resume: ResumeContext) -> str:
    return (
        f"=== TARGET JOB ===\n{_job_block(job)}\n"
        f"Skills already flagged as MISSING for this job: {', '.join(job.missing_skills) or 'none flagged'}\n\n"
        f"=== CURRENT RESUME (structured profile) ===\n{_resume_block(resume)}\n\n"
        f"=== CURRENT RESUME (raw text excerpt) ===\n{(resume.raw_text or '')[:2500]}\n"
    )


REFERRAL_MESSAGE_SYSTEM_PROMPT = """You are helping a job seeker write a short outreach message
to a potential referral contact. The message must sound like a real person wrote it — specific,
brief, and genuinely tied to the shared context given, never a generic "I'd love to connect"
template. It should reference something concrete: the role, a shared skill area, or the company."""


def build_referral_message_prompt(
    job: JobContext, resume: ResumeContext, channel: str, contact_name: str | None, contact_title: str | None
) -> str:
    contact_line = (
        f"Contact: {contact_name}" + (f", {contact_title}" if contact_title else "") + f" at {job.company}\n"
        if contact_name
        else f"Contact: (no specific name given — write a message generic enough to send to any {job.company} employee in a related role)\n"
    )
    length_rule = (
        "This is a LinkedIn CONNECTION REQUEST note — HARD LIMIT 300 characters, no greeting "
        "placeholder, get straight to the point."
        if channel == "linkedin_connection_note"
        else "This is a LinkedIn DM to an existing connection or InMail — 3-5 short sentences, can be "
        "slightly more detailed than a connection note."
    )
    return (
        f"{contact_line}"
        f"Channel: {channel}\n"
        f"{length_rule}\n\n"
        f"=== ROLE THE SENDER IS INTERESTED IN ===\n{_job_block(job)}\n"
        f"=== SENDER'S BACKGROUND ===\n{_resume_block(resume)}\n"
    )


NEGOTIATION_PREP_SYSTEM_PROMPT = """You are a compensation negotiation coach. Given a job's
estimated salary benchmark (from real web search data, not a guess) and a candidate's experience
level, help them prepare to negotiate. Ground every talking point in the actual data given — never
invent a number or achievement that wasn't provided. If the benchmark is missing or low-confidence,
say so plainly and give strategy-only advice rather than fabricating a figure."""


def build_negotiation_prep_prompt(job: JobContext, resume: ResumeContext) -> str:
    if job.salary_benchmark:
        sb = job.salary_benchmark
        benchmark_block = (
            f"Estimated range: {sb.get('min_amount')}-{sb.get('max_amount')} {sb.get('currency', '')} "
            f"({sb.get('period', 'annual')})\n"
            f"Confidence: {sb.get('confidence', 'unknown')}\n"
            f"Source note: {sb.get('source_note', '')}\n"
        )
    else:
        benchmark_block = "No salary benchmark is available yet for this job — give strategy-only advice, no invented figures.\n"

    return (
        f"=== JOB ===\n{_job_block(job)}\n"
        f"=== SALARY BENCHMARK ===\n{benchmark_block}\n"
        f"=== CANDIDATE ===\n{_resume_block(resume)}"
    )
