"""On-demand LLM call (FR-6): candid company/role assessment mined from a
job's own extracted signals (seniority, employment type, remote policy,
skills) plus its description — no resume needed, unlike the other Phase 6
features (this one isn't about candidate fit, just the employer/role
itself). Called by services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import COMPANY_RESEARCH_SYSTEM_PROMPT, build_company_research_prompt
from app.llm_tasks.schemas import CompanyResearchResult, JobContext


async def research_company(job: JobContext, llm: BaseChatModel) -> CompanyResearchResult:
    structured_llm = llm.with_structured_output(CompanyResearchResult)
    prompt = build_company_research_prompt(job)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=COMPANY_RESEARCH_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
