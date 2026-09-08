"""On-demand LLM call (FR-6, added alongside Phase 6 per user request):
salary negotiation prep — a natural pairing with Phase 4's automatic
salary_service.py enrichment, which already computes a web-search-backed
SalaryBenchmark for every saved job. This feature reuses that existing
Job.salary_benchmark rather than searching again; if it's missing or
low-confidence, the prompt instructs the model to give strategy-only advice
rather than invent a figure (same "ground it in real data or say you can't"
principle as salary_synthesis.py itself). Called by
services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import NEGOTIATION_PREP_SYSTEM_PROMPT, build_negotiation_prep_prompt
from app.llm_tasks.schemas import JobContext, NegotiationPrepResult, ResumeContext


async def prepare_negotiation(
    job: JobContext, resume: ResumeContext, llm: BaseChatModel
) -> NegotiationPrepResult:
    structured_llm = llm.with_structured_output(NegotiationPrepResult)
    prompt = build_negotiation_prep_prompt(job, resume)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=NEGOTIATION_PREP_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
