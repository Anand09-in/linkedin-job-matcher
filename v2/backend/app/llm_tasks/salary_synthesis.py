"""One-time-per-job LLM call that synthesizes web search results into a
SalaryBenchmark (FR-5.2). Called by services/salary_service.py."""
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import SALARY_SYNTHESIS_SYSTEM_PROMPT, build_salary_synthesis_prompt
from app.llm_tasks.schemas import SalaryBenchmark


async def synthesize_salary(
    job_title: str,
    company: str,
    location: Optional[str],
    experience_years_min: Optional[int],
    search_results_text: str,
    llm: BaseChatModel,
) -> SalaryBenchmark:
    structured_llm = llm.with_structured_output(SalaryBenchmark)
    prompt = build_salary_synthesis_prompt(job_title, company, location, experience_years_min, search_results_text)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=SALARY_SYNTHESIS_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
