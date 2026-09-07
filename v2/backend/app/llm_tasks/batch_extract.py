"""
The single structured-output LLM call that does extraction (FR-2.1) AND
matching (FR-2.2) for one batch, in one round trip — this is the core claim
of the whole redesign (plan.md Phase 3): no separate post-hoc "matching
pipeline" run exists.

Takes a pre-parsed ResumeProfile, not raw resume text — resume_parser.py
distills the resume into a compact profile ONCE per resume (cached in
Resume.parsed_profile); scrape_service.py resolves that once per run and
reuses it across every batch, instead of resending the full raw resume text
on every single call.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import SYSTEM_PROMPT, build_batch_prompt
from app.llm_tasks.schemas import BatchJobAnalysis, ResumeProfile
from app.scrapers.base import RawJob


async def analyze_batch(
    jobs: list[RawJob], resume_profile: Optional[ResumeProfile], llm: BaseChatModel
) -> BatchJobAnalysis:
    """
    One LLM call for the whole batch. Raises on LLM/parsing failure —
    services/scrape_service.py is responsible for catching that and marking
    the whole batch rejected (system-design.md §1.1: a batch failure rejects
    that batch, it does not abort the run) rather than this function
    silently degrading or retrying on its own.
    """
    if not jobs:
        return BatchJobAnalysis(results=[])

    structured_llm = llm.with_structured_output(BatchJobAnalysis)
    prompt = build_batch_prompt(jobs, resume_profile)

    logger.debug(f"[analyze_batch] {len(jobs)} jobs, resume={'yes' if resume_profile else 'no'}")

    async with llm_semaphore:
        result: BatchJobAnalysis = await structured_llm.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )

    if resume_profile is None:
        # Deterministic override — don't rely on the LLM having followed the
        # "no profile -> don't score" prompt instruction perfectly.
        # system-design.md §3.3: the LLM scores, the system decides; this
        # extends that to "the system decides whether scoring even applies."
        for item in result.results:
            item.match_score = None
            item.matched_skills = []
            item.missing_skills = []
            item.match_rationale = None

    if len(result.results) != len(jobs):
        logger.warning(
            f"[analyze_batch] expected {len(jobs)} results, got {len(result.results)} "
            f"— reassembly by job_index may be incomplete"
        )

    return result
