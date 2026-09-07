"""
LLM Factory — returns a LangChain BaseChatModel for any supported provider.

Ported from v1's config/llm_factory.py, including the ChatBedrockConverse fix
(v1 originally used ChatBedrock + provider-specific model_kwargs, which sent a
malformed body for Mistral Large — "missing field messages" — because it
lumped mistral.* in with meta.*'s raw-completion format. ChatBedrockConverse
uses Bedrock's unified Converse API, which formats messages correctly per
model without that branching. See v1 config/llm_factory.py history.)

architecture.md §1 / FR-3: this is the ONLY place any code constructs an LLM
client — extraction+matching (llm_tasks/batch_extract.py), salary synthesis
(services/salary_service.py), and every on-demand feature all call get_llm()
here. Phase 5 adds reading the active provider/model from the DB LLM_SETTING
row instead of only env vars; Phase 0 only needs the provider mechanics.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


def get_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """
    Build and return a LangChain chat model for the configured provider.

    Unlike v1's per-feature model/provider overrides, v2 callers should
    normally call get_llm() with no arguments — the active provider/model
    comes from Settings (Phase 0: env vars; Phase 5: DB LLM_SETTING, FR-3.1/3.2).
    Explicit args remain for tests.
    """
    p = (provider or settings.llm_provider).lower()
    m = model or (settings.bedrock_model if p == "bedrock" else settings.llm_model)
    temp = temperature if temperature is not None else settings.llm_temperature
    max_tok = max_tokens or settings.llm_max_tokens

    logger.debug(f"[LLM] provider={p} model={m} temperature={temp}")

    if p == "bedrock":
        return _build_bedrock(m, temp, max_tok)
    elif p == "anthropic":
        return _build_anthropic(m, temp, max_tok)
    elif p in ("openai", "groq"):
        return _build_openai_compat(p, m, temp, max_tok)
    elif p == "gemini":
        return _build_gemini(m, temp, max_tok)
    elif p == "ollama":
        return _build_ollama(m, temp)
    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{p}'. "
            f"Valid: bedrock | anthropic | openai | groq | gemini | ollama"
        )


# ── Provider builders ─────────────────────────────────────────────────────────

def _build_bedrock(model: str, temperature: float, max_tokens: int) -> BaseChatModel:
    """
    Amazon Bedrock via langchain-aws, using the Converse API.

    Supported chat model families:
        anthropic.claude-*          ← best quality
        meta.llama*                 ← free tier, good speed
        mistral.*                   ← free tier, incl. mistral-large (chat/messages format)
        amazon.nova-*               ← Amazon's own models

    NOT supported for chat (text-generation only):
        google.gemma-*
        amazon.titan-text-*
        cohere.command-text-*
    """
    _NO_CHAT_PREFIXES = ("google.", "amazon.titan-text", "cohere.command-text")
    if any(model.startswith(p) for p in _NO_CHAT_PREFIXES):
        raise ValueError(
            f"Bedrock model '{model}' does not support the chat API format. "
            f"Use a chat-compatible model instead: "
            f"anthropic.claude-3-haiku-20240307-v1:0 | "
            f"mistral.mistral-large-2407-v1:0"
        )

    try:
        from langchain_aws import ChatBedrockConverse
        import boto3

        session_kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id:
            session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        boto_session = boto3.Session(**session_kwargs)
        bedrock_client = boto_session.client("bedrock-runtime")

        # Converse API normalizes the request/response shape across all
        # Bedrock providers (Anthropic, Meta, Mistral, Amazon, …), so no
        # per-provider max_tokens/max_gen_len branching is needed here.
        return ChatBedrockConverse(
            client=bedrock_client,
            model_id=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ImportError:
        raise ImportError("Run: pip install langchain-aws boto3")


def _build_anthropic(model: str, temperature: float, max_tokens: int) -> BaseChatModel:
    """Anthropic direct API."""
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except ImportError:
        raise ImportError("Run: pip install langchain-anthropic")


def _build_openai_compat(provider: str, model: str, temperature: float, max_tokens: int) -> BaseChatModel:
    """
    OpenAI-compatible endpoint — works for both OpenAI and Groq.
    Groq uses OpenAI-compatible API, so we just swap the base_url and api_key.
    """
    try:
        from langchain_openai import ChatOpenAI

        if provider == "groq":
            return ChatOpenAI(
                model=model,
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            return ChatOpenAI(
                model=model,
                api_key=settings.openai_api_key,
                temperature=temperature,
                max_tokens=max_tokens,
            )
    except ImportError:
        raise ImportError("Run: pip install langchain-openai")


def _build_gemini(model: str, temperature: float, max_tokens: int) -> BaseChatModel:
    """Google Gemini via langchain-google-genai."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
    except ImportError:
        raise ImportError("Run: pip install langchain-google-genai")


def _build_ollama(model: str, temperature: float) -> BaseChatModel:
    """Local Ollama — no API key, fully free."""
    try:
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )
    except ImportError:
        raise ImportError("Run: pip install langchain-community")
