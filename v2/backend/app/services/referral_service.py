"""
Referral-contact search — surfaces potential referral contacts at a job's
company. On-demand, triggered per job by the user (same pattern as the
Phase 6 on-demand features: cover letter, interview prep, etc.), NOT run
automatically for every saved job like salary enrichment.

Deliberately web-search-only, NOT LinkedIn scraping — a direct design
decision, not a shortcut: LinkedIn treats automated scraping of member/
profile data far more seriously than job listings (it's explicitly called
out in their Terms of Service), and this project already saw LinkedIn's
rate-limiting kick in after just a handful of automated job-search requests
in one session (Phase 2 testing). Adding LinkedIn people-search automation
on top of that — especially automatically, for every saved job — would risk
the account, including the job-scraping capability that already works. This
module only ever searches the public web (DuckDuckGo via ddgs, the same
mechanism as salary_service.py) for publicly indexed LinkedIn profile
snippets — no li_at cookie, no LinkedIn automation, no session risk.

Surfacing only: this returns names/titles/profile links for the user to
reach out to themselves. Nothing here initiates any messaging, connection
request, or other outreach — that would be a materially different, riskier
feature and isn't part of this one.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from app.llm_tasks.referral_synthesis import synthesize_referral_contacts
from app.llm_tasks.schemas import ReferralSearchResult
from app.services.web_search import format_snippets, web_search


def _build_query(company: str, job_title: str) -> str:
    return f'site:linkedin.com/in "{company}" {job_title}'


async def find_referral_contacts(company: str, job_title: str, llm: BaseChatModel) -> ReferralSearchResult:
    query = _build_query(company, job_title)
    results = await web_search(query, max_results=8)
    snippets = format_snippets(results)
    return await synthesize_referral_contacts(company, job_title, snippets, llm)
