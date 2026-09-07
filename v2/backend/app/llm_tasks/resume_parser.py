"""
One-time resume parsing — distills a raw resume into a compact ResumeProfile
that gets reused across every batch call for every pipeline bound to that
resume, instead of resending the full raw resume text on every single call.

Raised directly by a real usage question: LLM APIs are stateless per call —
there's no server-side memory across separate requests, so the resume must
physically be in each request for the model to use it that call. What this
changes is WHAT gets resent: a small structured profile, computed once and
cached (Resume.parsed_profile), instead of the full raw text every time.
scrape_service.py is responsible for the caching — this module just does the
one LLM call.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import RESUME_PARSE_SYSTEM_PROMPT, build_resume_parse_prompt
from app.llm_tasks.schemas import ResumeProfile


async def parse_resume(raw_text: str, llm: BaseChatModel) -> ResumeProfile:
    structured_llm = llm.with_structured_output(ResumeProfile)
    prompt = build_resume_parse_prompt(raw_text)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=RESUME_PARSE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
