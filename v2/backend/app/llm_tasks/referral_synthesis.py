"""On-demand LLM call that synthesizes public web search results into a
ReferralSearchResult. Called by services/referral_service.py — see that
module's docstring for why this is web-search-only, not LinkedIn scraping."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import REFERRAL_SYNTHESIS_SYSTEM_PROMPT, build_referral_synthesis_prompt
from app.llm_tasks.schemas import ReferralSearchResult


async def synthesize_referral_contacts(
    company: str, job_title: str, search_results_text: str, llm: BaseChatModel
) -> ReferralSearchResult:
    structured_llm = llm.with_structured_output(ReferralSearchResult)
    prompt = build_referral_synthesis_prompt(company, job_title, search_results_text)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=REFERRAL_SYNTHESIS_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
