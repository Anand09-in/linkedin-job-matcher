"""On-demand LLM call (FR-6): generates 12 tailored interview questions
across 4 categories for one job/resume pair. Called by
services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import INTERVIEW_PREP_SYSTEM_PROMPT, build_interview_prep_prompt
from app.llm_tasks.schemas import InterviewPrepResult, JobContext, ResumeContext


async def generate_interview_prep(
    job: JobContext, resume: ResumeContext, llm: BaseChatModel
) -> InterviewPrepResult:
    structured_llm = llm.with_structured_output(InterviewPrepResult)
    prompt = build_interview_prep_prompt(job, resume)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=INTERVIEW_PREP_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
