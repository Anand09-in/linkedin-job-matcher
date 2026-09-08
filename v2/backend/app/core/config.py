"""
Centralized settings — env-driven (architecture.md §1: no config.yaml, no
.env-only-for-secrets split; everything runtime-tunable moves to Postgres in
later phases, but connection/secret config stays here per system-design.md §4).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

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

    # Batch extraction (analyze_batch) returns up to 5 full structured
    # results in one response — the default llm_max_tokens (sized for a
    # single-feature call) isn't enough headroom. Confirmed live: a 2-job
    # batch under the default budget hit the token ceiling mid-response and
    # degenerated into a runaway, incomplete result. Kept as its own setting
    # rather than just raising llm_max_tokens globally, since single-feature
    # calls (cover letter, etc.) don't need this much room.
    llm_batch_extract_max_tokens: int = Field(4000)

    # interview_prep (Phase 6/FR-6) is a single-feature call but, unlike
    # cover letter/company research/etc., its structured output is a 12-item
    # list of richly detailed objects — comparably large to a batch
    # extraction response, not a normal single-feature one. Confirmed live:
    # under the default llm_max_tokens budget, Mistral Large truncated mid-
    # item (a 9th question left with only its `category` field), which
    # without schemas.py's InterviewPrepResult._sanitize_questions backstop
    # would crash the whole feature call. Same fix pattern as
    # llm_batch_extract_max_tokens above — its own setting, not a global
    # bump, since most single-feature calls don't need this much room.
    llm_interview_prep_max_tokens: int = Field(4000)

    # Cap on concurrent in-flight Bedrock calls across ALL pipelines in this
    # worker process (system-design.md §2.3) — sized conservatively since the
    # "safe" number is account-tier-specific; v1 had to serialize Bedrock
    # calls entirely (max_workers=1) after hitting ThrottlingException.
    llm_max_concurrent_calls: int = Field(2)

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = Field("us-east-1")
    bedrock_model: str = Field("anthropic.claude-3-haiku-20240307-v1:0")

    # ── LinkedIn (needed once scrapers/linkedin lands in Phase 2) ───────────────
    li_at_cookie: str = Field("", description="LinkedIn li_at session cookie")

    # ── Matching defaults (FR-1A.4) — a Pipeline may override either; these
    #    are the system-wide fallback when it doesn't, not hardcoded in the
    #    filter logic itself. ─────────────────────────────────────────────────
    default_min_match_score: float = Field(0.40)
    default_max_experience_years: Optional[int] = Field(None)

    # ── CORS (Phase 8) — the frontend (localhost:5173 by default) and the API
    #    (localhost:8000) are different origins even on the same machine, since
    #    they differ by port; the browser enforces CORS regardless of both
    #    being "localhost". Comma-separated so FRONTEND_PORT/a prod domain can
    #    be added via env without a code change. http://frontend:5173 (the
    #    Compose service's own hostname) is included for container-to-
    #    container browser verification (e.g. a Playwright script running
    #    inside the worker container) — harmless for real usage, since a
    #    real user's browser is never actually served from that origin.
    cors_allowed_origins: str = Field("http://localhost:5173,http://127.0.0.1:5173,http://frontend:5173")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
