"""On-demand LLM call (FR-6, 2026-09-08): generates cover_letter +
interview_prep + company_research + resume_improvement in ONE
structured-output call instead of four separate ones — added per explicit
user request. referral_message and referral_search stay separate calls
(see AllFeaturesResult's docstring for why bundling those wouldn't make
sense). Called by services/feature_service.py."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import ALL_FEATURES_SYSTEM_PROMPT, build_all_features_prompt
from app.llm_tasks.schemas import AllFeaturesResult, JobContext, ResumeContext


async def generate_all_features(
    job: JobContext, resume: ResumeContext, tone: str, word_count: int, llm: BaseChatModel
) -> AllFeaturesResult:
    structured_llm = llm.with_structured_output(AllFeaturesResult)
    prompt = build_all_features_prompt(job, resume, tone, word_count)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=ALL_FEATURES_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
