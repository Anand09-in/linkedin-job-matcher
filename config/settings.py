"""
Centralised settings — reads .env and config.yaml.
All other modules import from here; never import dotenv elsewhere.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # ── LinkedIn ──────────────────────────────────────────────────────────────
    li_at_cookie: str = Field("", description="LinkedIn li_at session cookie")

    # ── LLM provider (swap with one env var) ──────────────────────────────────
    llm_provider: str = Field("groq", description="anthropic|openai|groq|ollama|gemini|bedrock")
    llm_model: str = Field("llama3-8b-8192")
    llm_temperature: float = Field(0.1)
    llm_max_tokens: int = Field(2000)

    # Direct provider keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    google_api_key: str = ""

    # Ollama (local)
    ollama_base_url: str = "http://localhost:11434"

    # ── Amazon Bedrock ────────────────────────────────────────────────────────
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = Field("us-east-1", description="AWS region where Bedrock is enabled")
    # Default Bedrock model — Claude 3 Haiku is cheapest on free tier
    bedrock_model: str = Field(
        "anthropic.claude-3-haiku-20240307-v1:0",
        description="Bedrock model ID. Free tier options: "
                    "anthropic.claude-3-haiku-20240307-v1:0 | "
                    "meta.llama3-8b-instruct-v1:0 | "
                    "mistral.mistral-7b-instruct-v0:2",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = f"sqlite+aiosqlite:///{ROOT}/data/jobs.db"

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler_enabled: bool = Field(False, description="Auto-run scraper in background")
    scheduler_interval_hours: int = Field(12, description="Scrape interval in hours")

    # ── Scraper backoff ───────────────────────────────────────────────────────
    scraper_backoff_base: float = Field(5.0, description="Base seconds for exponential backoff on 429")

    @property
    def yaml_config(self) -> dict:
        text = (ROOT / "config" / "config.yaml").read_text()
        for k, v in os.environ.items():
            text = text.replace(f"${{{k}}}", v)
        return yaml.safe_load(text)

    def validate_all(self) -> None:
        """
        Full startup validation. Called from api/main.py lifespan.

        Fatal (sys.exit):  data directory not writable
        Warning (logged):  missing cookie, missing LLM key
        """
        import sys
        from pathlib import Path

        # ── 1. Data directory ─────────────────────────────────────────────────
        db_path = self.database_url.split("///")[-1]
        data_dir = Path(db_path).parent
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.critical(f"[Startup] Cannot create data dir {data_dir}: {e}")
            sys.exit(1)

        probe = data_dir / ".write_probe"
        try:
            probe.touch()
            probe.unlink()
            logger.info(f"[Startup] Data directory OK: {data_dir}")
        except OSError as e:
            logger.critical(f"[Startup] Data directory {data_dir} not writable: {e}")
            sys.exit(1)

        # ── 2. LinkedIn cookie ────────────────────────────────────────────────
        if not self.li_at_cookie:
            logger.warning(
                "[Startup] LI_AT_COOKIE not set — scraping will fail. "
                "Set it in .env (LinkedIn DevTools → Application → Cookies → li_at)"
            )

        # ── 3. LLM credentials ────────────────────────────────────────────────
        try:
            self.validate_llm_config()
            logger.info("[Startup] LLM config valid ✓")
        except ValueError as e:
            logger.warning(f"[Startup] LLM config warning: {e} — AI features may fail")

    def validate_llm_config(self) -> None:
        """Raise early with a clear message if required keys are missing."""
        p = self.llm_provider.lower()
        if p == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if p == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if p == "groq" and not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        if p == "gemini" and not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")
        if p == "bedrock":
            # Allow IAM role auth (no keys needed on EC2/Lambda) or explicit keys
            if not self.aws_access_key_id and not os.environ.get("AWS_PROFILE"):
                raise ValueError(
                    "For Bedrock: set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY "
                    "or configure an AWS_PROFILE / IAM role"
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
