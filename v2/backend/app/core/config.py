"""
Centralized settings — env-driven (architecture.md §1: no config.yaml, no
.env-only-for-secrets split; everything runtime-tunable moves to Postgres in
later phases, but connection/secret config stays here per system-design.md §4).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent.parent  # v2/backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Database (Postgres — architecture.md §1, decision #1) ──────────────────
    database_url: str = Field(
        "postgresql+asyncpg://postgres:postgres@postgres:5432/job_matcher",
        description="Async SQLAlchemy URL used by the API/worker at runtime",
    )

    # ── Task queue / cache (Redis — architecture.md §1) ─────────────────────────
    redis_url: str = Field("redis://redis:6379/0")

    # ── LLM — Bedrock only (FR-3, narrowed by explicit user decision: no
    #    Anthropic-direct/OpenAI/Groq/Gemini/Ollama support in v2 at all) ───────
    llm_temperature: float = Field(0.1)
    llm_max_tokens: int = Field(2000)

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = Field("us-east-1")
    bedrock_model: str = Field("anthropic.claude-3-haiku-20240307-v1:0")

    # ── LinkedIn (needed once scrapers/linkedin lands in Phase 2) ───────────────
    li_at_cookie: str = Field("", description="LinkedIn li_at session cookie")


@lru_cache
def get_settings() -> Settings:
    return Settings()
