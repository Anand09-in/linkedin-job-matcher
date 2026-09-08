"""On-demand LLM call (FR-6): generates a tailored cover letter for one job/
resume pair. Called by services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import COVER_LETTER_SYSTEM_PROMPT, build_cover_letter_prompt
from app.llm_tasks.schemas import CoverLetterResult, JobContext, ResumeContext


async def generate_cover_letter(
    job: JobContext, resume: ResumeContext, tone: str, word_count: int, llm: BaseChatModel
) -> CoverLetterResult:
    structured_llm = llm.with_structured_output(CoverLetterResult)
    prompt = build_cover_letter_prompt(job, resume, tone, word_count)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=COVER_LETTER_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
