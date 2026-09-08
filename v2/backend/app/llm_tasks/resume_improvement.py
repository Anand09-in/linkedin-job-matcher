"""On-demand LLM call (FR-6): job-specific resume improvement suggestions —
distinct from resume_parser.py's one-time ResumeProfile distillation, this
runs per (job, resume) pair and reads the raw resume text for a deeper
excerpt than the condensed profile carries. Called by
services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import RESUME_IMPROVEMENT_SYSTEM_PROMPT, build_resume_improvement_prompt
from app.llm_tasks.schemas import JobContext, ResumeContext, ResumeImprovementResult


async def improve_resume(
    job: JobContext, resume: ResumeContext, llm: BaseChatModel
) -> ResumeImprovementResult:
    structured_llm = llm.with_structured_output(ResumeImprovementResult)
    prompt = build_resume_improvement_prompt(job, resume)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=RESUME_IMPROVEMENT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
