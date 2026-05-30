"""
JDParser — extracts structured requirements from a raw job description.

Uses the active LLM (any provider) via llm_factory.
Retries on transient failures via tenacity.
Validates output against ParsedJD schema before returning.

Phase 2.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.llm_factory import get_llm
from parser.schemas import ParsedJD

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert technical recruiter and HR analyst.
Your job is to extract structured information from job descriptions.
Always respond with valid JSON only — no markdown, no backticks, no explanation.
If a field cannot be determined from the text, use null.
Skill names should be short and lowercase (e.g. "python", "pytorch", "aws s3").\
"""

_USER_PROMPT_TEMPLATE = """\
Extract structured information from the following job description and return a JSON object.

Return ONLY this JSON structure (no other text):
{{
  "skills_required": ["list of must-have technical skills, tools, frameworks"],
  "skills_nice_to_have": ["optional/preferred skills"],
  "experience_years": "human-readable string e.g. '3-5 years' or null",
  "experience_years_min": <integer lower bound or null>,
  "seniority_level": "one of: Entry | Junior | Mid | Senior | Lead | Principal | Manager | null",
  "employment_type": "one of: Full-time | Part-time | Contract | Internship | null",
  "remote_policy": "one of: Remote | Hybrid | On-site | Flexible | null",
  "education_required": "e.g. 'Bachelor in Computer Science' or null",
  "salary_range": "e.g. '15-25 LPA' or '80k-120k USD' or null",
  "responsibilities": ["key responsibilities, max 5 bullet points"],
  "company_info": {{
    "size_hint": "one of: startup | mid-size | enterprise | null",
    "domain": "industry domain e.g. fintech | healthtech | ecommerce | saas | null"
  }}
}}

Job description:
---
{description}
---\
"""


# ─────────────────────────────────────────────────────────────────────────────

class JDParser:
    """
    Parses a raw job description string into a structured ParsedJD object.

    Usage:
        parser = JDParser()
        result: ParsedJD = parser.parse(description)
    """

    def __init__(self, llm: Optional[BaseChatModel] = None) -> None:
        self._llm = llm or get_llm()

    # ── Core parse with retry ─────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((ValueError, json.JSONDecodeError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_llm(self, description: str) -> dict:
        """Send JD to LLM, get raw JSON dict back. Retried up to 3×."""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_USER_PROMPT_TEMPLATE.format(description=description)),
        ]
        response = self._llm.invoke(messages)
        raw = response.content.strip()

        # Strip markdown code fences if model added them despite instructions
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM returned non-dict JSON: {type(parsed)}")
        return parsed

    def parse(self, description: str) -> ParsedJD:
        """
        Parse a job description string into a validated ParsedJD.

        Args:
            description: raw text of the job posting

        Returns:
            ParsedJD — validated Pydantic model

        Raises:
            ValueError: if LLM returns unparseable output after all retries
            pydantic.ValidationError: if output fails schema validation
        """
        if not description or not description.strip():
            logger.warning("[JDParser] Empty description — returning empty ParsedJD")
            return ParsedJD()

        # Truncate very long JDs to stay within token limits
        # Most models handle 4k tokens well; ~4 chars per token → 16k chars
        max_chars = 16_000
        if len(description) > max_chars:
            logger.warning(f"[JDParser] Description truncated from {len(description)} to {max_chars} chars")
            description = description[:max_chars]

        try:
            raw_dict = self._call_llm(description)
            result = ParsedJD.model_validate(raw_dict)
            logger.info(
                f"[JDParser] OK — skills={len(result.skills_required)} "
                f"seniority={result.seniority_level} "
                f"exp={result.experience_years}"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[JDParser] JSON parse failed after retries: {e}")
            return ParsedJD()   # return empty rather than crash the whole pipeline

        except ValidationError as e:
            logger.error(f"[JDParser] Schema validation failed: {e}")
            return ParsedJD()

        except Exception as e:
            logger.error(f"[JDParser] Unexpected error: {e}")
            return ParsedJD()

    def parse_batch(self, descriptions: list[str]) -> list[ParsedJD]:
        """
        Parse a list of job descriptions sequentially.
        Returns a list of ParsedJD (same length as input, empty objects for failures).
        """
        results = []
        for i, desc in enumerate(descriptions):
            logger.info(f"[JDParser] Parsing JD {i+1}/{len(descriptions)}")
            results.append(self.parse(desc))
        return results
