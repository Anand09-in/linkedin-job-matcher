"""On-demand LLM call (FR-6, added alongside Phase 6 per user request): drafts
a short outreach message to a referral contact — a natural pairing with
Phase 4's referral_service.py (which only surfaces contacts, never drafts
outreach). Surfacing/drafting only: this module never sends anything, it
just returns text for the user to review, edit, and send themselves. Called
by services/feature_service.py."""
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import llm_semaphore
from app.llm_tasks.prompts import REFERRAL_MESSAGE_SYSTEM_PROMPT, build_referral_message_prompt
from app.llm_tasks.schemas import JobContext, ReferralMessageResult, ResumeContext


async def draft_referral_message(
    job: JobContext,
    resume: ResumeContext,
    llm: BaseChatModel,
    channel: str = "linkedin_connection_note",
    contact_name: Optional[str] = None,
    contact_title: Optional[str] = None,
) -> ReferralMessageResult:
    structured_llm = llm.with_structured_output(ReferralMessageResult)
    prompt = build_referral_message_prompt(job, resume, channel, contact_name, contact_title)

    async with llm_semaphore:
        return await structured_llm.ainvoke(
            [SystemMessage(content=REFERRAL_MESSAGE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
