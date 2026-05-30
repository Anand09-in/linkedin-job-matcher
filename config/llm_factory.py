"""
LLM Factory — returns a LangChain BaseChatModel for any supported provider.

Swap your entire LLM by changing ONE line in .env:
    LLM_PROVIDER=bedrock
    LLM_MODEL=anthropic.claude-3-haiku-20240307-v1:0

All parsers and pipeline nodes call get_llm() and never import a
provider-specific class directly — this is the only place that knows
which provider is active.

Supported providers:
    bedrock   — Amazon Bedrock (Claude Haiku, Llama3, Mistral — AWS free tier)
    groq      — Groq (Llama3-8b free tier, fastest)
    anthropic — Anthropic direct API (Claude Haiku)
    openai    — OpenAI API (GPT-4o-mini cheapest)
    gemini    — Google Gemini (Flash free tier)
    ollama    — Local Ollama (fully free, no API key)
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from langchain_core.language_models import BaseChatModel
from loguru import logger

from config.settings import get_settings

settings = get_settings()


def get_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """
    Build and return a LangChain chat model for the configured provider.

    Args:
        provider:    override LLM_PROVIDER env var (useful in tests)
        model:       override LLM_MODEL env var
        temperature: override default temperature
        max_tokens:  override default max_tokens

    Returns:
        A LangChain BaseChatModel — same interface regardless of provider.
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
    Amazon Bedrock via langchain-aws.

    Recommended free-tier models:
        anthropic.claude-3-haiku-20240307-v1:0   ← best quality/cost
        meta.llama3-8b-instruct-v1:0
        mistral.mistral-7b-instruct-v0:2

    Auth (pick one):
        1. Set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY in .env
        2. Configure ~/.aws/credentials (aws configure)
        3. Use an IAM role (on EC2/Lambda — no keys needed)
    """
    try:
        from langchain_aws import ChatBedrock
        import boto3

        # Build boto3 session — uses env vars or ~/.aws/credentials automatically
        session_kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id:
            session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        boto_session = boto3.Session(**session_kwargs)
        bedrock_client = boto_session.client("bedrock-runtime")

        # model_kwargs varies by model family
        model_kwargs: dict = {"temperature": temperature}
        if model.startswith("anthropic.") or model.startswith("amazon."):
            model_kwargs["max_tokens"] = max_tokens
        elif model.startswith("meta.") or model.startswith("mistral."):
            model_kwargs["max_gen_len"] = max_tokens  # Llama/Mistral use max_gen_len

        return ChatBedrock(
            client=bedrock_client,
            model_id=model,
            model_kwargs=model_kwargs,
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
