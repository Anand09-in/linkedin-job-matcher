"""
LLM Factory — Amazon Bedrock only.

v2 deliberately supports exactly one provider (explicit user decision — no
Anthropic-direct, OpenAI, Groq, Gemini, or Ollama). This is narrower than
v1's config/llm_factory.py, which supported six providers; FR-3.1 already
called for "one model for all," and Bedrock-only is the concrete form that
took. If a second provider is ever needed again, reintroduce it as a
deliberate, separate decision — don't resurrect the old branching from git
history by default.

Includes the ChatBedrockConverse fix carried over from v1: ChatBedrock +
provider-specific model_kwargs sent a malformed body for Mistral Large
("missing field messages") because it lumped mistral.* in with meta.*'s
raw-completion format. ChatBedrockConverse uses Bedrock's unified Converse
API, which formats messages correctly per model without that branching.

architecture.md §1 / FR-3: this is the ONLY place any code constructs an LLM
client — extraction+matching (llm_tasks/batch_extract.py), salary synthesis
(services/salary_service.py), and every on-demand feature all call get_llm()
here.

Phase 5 (FR-3.2): get_llm() is now async and reads the active model from the
DB LLMSetting row (via PUT /settings/llm — main.py) — changing the active
model takes effect on the very next call, no container restart, matching
the exit criteria in plan.md Phase 5. Falls back to the BEDROCK_MODEL env
var only if no LLMSetting row exists yet (first boot, before anyone has set
one via the API).

`llm_semaphore` (system-design.md §2.3) caps concurrent in-flight Bedrock
calls across ALL pipelines in this worker process — sequential within one
pipeline's own scrape loop already happens naturally (analyze_batch is
awaited one batch at a time), so this only matters once two pipelines run
concurrently. Every call site (analyze_batch now; salary synthesis and
on-demand features later) is expected to `async with llm_semaphore:` around
its actual `.invoke()`/`.ainvoke()` call, not around get_llm() itself.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from langchain_core.language_models import BaseChatModel
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

llm_semaphore = asyncio.Semaphore(settings.llm_max_concurrent_calls)

_NO_CHAT_PREFIXES = ("google.", "amazon.titan-text", "cohere.command-text")


async def _get_active_llm_setting():
    """Isolated import to avoid a hard module-level dependency from
    core/llm.py (a low-level factory) on the domain/DB layer — only this
    function touches it, and only when a call site didn't explicitly
    override every field."""
    from app.domain.db import AsyncSessionLocal
    from app.domain.repository import Repository

    async with AsyncSessionLocal() as session:
        return await Repository(session).get_active_llm_setting()


async def get_llm(
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """
    Build and return a LangChain chat model for Bedrock.

    Callers should normally call get_llm() with no arguments — the active
    model/temperature/max_tokens come from the DB LLMSetting row (FR-3.1/
    3.2), falling back to env vars only if none has been set yet. Explicit
    args always win over the DB setting (e.g. scrape_service.py's larger
    batch-extraction max_tokens) — they're an override, not a default.
    """
    active = None
    if model is None or temperature is None or max_tokens is None:
        active = await _get_active_llm_setting()

    m = model or (active.model if active else None) or settings.bedrock_model
    temp = temperature if temperature is not None else (active.temperature if active else settings.llm_temperature)
    max_tok = max_tokens or (active.max_tokens if active else settings.llm_max_tokens)

    logger.debug(f"[LLM] provider=bedrock model={m} temperature={temp}")

    if any(m.startswith(p) for p in _NO_CHAT_PREFIXES):
        raise ValueError(
            f"Bedrock model '{m}' does not support the chat API format. "
            f"Use a chat-compatible model instead: "
            f"anthropic.claude-3-haiku-20240307-v1:0 | "
            f"mistral.mistral-large-2407-v1:0"
        )

    from langchain_aws import ChatBedrockConverse
    import boto3

    session_kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id:
        session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    boto_session = boto3.Session(**session_kwargs)
    bedrock_client = boto_session.client("bedrock-runtime")

    # Converse API normalizes the request/response shape across all Bedrock
    # model families (Anthropic, Meta, Mistral, Amazon, …), so no
    # per-provider max_tokens/max_gen_len branching is needed here.
    return ChatBedrockConverse(
        client=bedrock_client,
        model_id=m,
        temperature=temp,
        max_tokens=max_tok,
    )
