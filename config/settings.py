"""
Centralised settings — reads .env and config.yaml.
All other modules import from here; never import dotenv elsewhere.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
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

    @property
    def yaml_config(self) -> dict:
        text = (ROOT / "config" / "config.yaml").read_text()
        for k, v in os.environ.items():
            text = text.replace(f"${{{k}}}", v)
        return yaml.safe_load(text)

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
