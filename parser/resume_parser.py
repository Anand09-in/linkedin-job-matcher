"""
ResumeParser — extracts structured candidate profile from a PDF resume.

Two-step process:
  1. extract_text()  — PDF bytes → clean raw text (using pymupdf)
  2. parse()         — raw text → ParsedResume via LLM

Uses the active LLM (any provider) via llm_factory.
Retries on transient failures via tenacity.

Phase 2.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
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
from parser.schemas import ParsedResume

# ── Prompts ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert resume analyst and technical recruiter.
Extract structured information from the resume text provided.
Always respond with valid JSON only — no markdown, no backticks, no explanation.
Skill and tool names should be short and lowercase (e.g. "python", "pytorch", "aws").
If a field cannot be determined, use null or an empty list.\
"""

_USER_PROMPT_TEMPLATE = """\
Extract structured information from the following resume and return a JSON object.

Return ONLY this JSON structure (no other text):
{{
  "name": "candidate full name or null",
  "current_title": "most recent job title or null",
  "total_experience_years": <number e.g. 3.5 or null>,
  "summary": "2-3 sentence professional summary or null",
  "skills": ["technical skills list — algorithms, ML concepts, methodologies"],
  "tools": ["tools, frameworks, libraries, platforms e.g. pytorch, kafka, docker"],
  "languages": ["programming languages e.g. python, java, sql"],
  "certifications": ["certifications and courses"],
  "work_history": [
    {{
      "title": "job title",
      "company": "company name",
      "duration_years": <float or null>,
      "description": "one-line summary of role"
    }}
  ],
  "education": [
    {{
      "degree": "e.g. B.Tech | M.S. | PhD",
      "institution": "university name",
      "year": <graduation year integer or null>,
      "field": "e.g. Computer Science | Electrical Engineering"
    }}
  ]
}}

Resume text:
---
{resume_text}
---\
"""


# ─────────────────────────────────────────────────────────────────────────────

class ResumeParser:
    """
    Extracts a structured ParsedResume from a PDF file.

    Usage:
        parser = ResumeParser()
        raw_text = parser.extract_text(pdf_bytes)
        profile = parser.parse(raw_text)
    """

    def __init__(self, llm: Optional[BaseChatModel] = None) -> None:
        self._llm = llm or get_llm()

    # ── PDF text extraction ───────────────────────────────────────────────────

    def extract_text(self, pdf_bytes: bytes) -> str:
        """
        Extract clean text from PDF bytes using pymupdf (fitz).

        Falls back to pdfplumber if fitz fails (e.g. scanned / image PDF).

        Args:
            pdf_bytes: raw bytes of the PDF file

        Returns:
            Extracted text as a single string.
        """
        # Try pymupdf first (fast, handles most PDFs)
        try:
            import fitz  # pymupdf

            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages = []
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    pages.append(text)
            doc.close()

            full_text = "\n".join(pages).strip()
            if full_text:
                logger.info(f"[ResumeParser] Extracted {len(full_text)} chars via pymupdf")
                return self._clean_text(full_text)

        except Exception as e:
            logger.warning(f"[ResumeParser] pymupdf failed: {e} — trying pdfplumber")

        # Fallback: pdfplumber (better for table-heavy resumes)
        try:
            import io
            import pdfplumber

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            full_text = "\n".join(pages).strip()
            if full_text:
                logger.info(f"[ResumeParser] Extracted {len(full_text)} chars via pdfplumber")
                return self._clean_text(full_text)

        except Exception as e:
            logger.error(f"[ResumeParser] pdfplumber also failed: {e}")

        logger.error("[ResumeParser] Both extraction methods failed — returning empty string")
        return ""

    def extract_text_from_path(self, path: str | Path) -> str:
        """Convenience method — read PDF from disk path."""
        pdf_bytes = Path(path).read_bytes()
        return self.extract_text(pdf_bytes)

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove excessive whitespace, null bytes, and other PDF artifacts."""
        # Remove null bytes
        text = text.replace("\x00", "")
        # Collapse multiple blank lines to two
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove leading/trailing whitespace per line
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(lines).strip()

    # ── LLM parsing with retry ────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((ValueError, json.JSONDecodeError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_llm(self, resume_text: str) -> dict:
        """Send resume text to LLM, get raw JSON dict back. Retried up to 3×."""
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_USER_PROMPT_TEMPLATE.format(resume_text=resume_text)),
        ]
        response = self._llm.invoke(messages)
        raw = response.content.strip()

        # Strip markdown fences if model adds them
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM returned non-dict: {type(parsed)}")
        return parsed

    def parse(self, raw_text: str) -> ParsedResume:
        """
        Parse raw resume text into a validated ParsedResume.

        Args:
            raw_text: extracted text from PDF (call extract_text() first)

        Returns:
            ParsedResume — validated Pydantic model

        Raises:
            ValueError: if text is empty
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("Resume text is empty — check that the PDF extracted correctly")

        # Trim to token budget (~16k chars ≈ 4k tokens, fits all common models)
        max_chars = 16_000
        if len(raw_text) > max_chars:
            logger.warning(f"[ResumeParser] Text truncated from {len(raw_text)} to {max_chars} chars")
            raw_text = raw_text[:max_chars]

        try:
            raw_dict = self._call_llm(raw_text)
            result = ParsedResume.model_validate(raw_dict)
            logger.info(
                f"[ResumeParser] OK — "
                f"name={result.name} "
                f"title={result.current_title} "
                f"exp={result.total_experience_years}y "
                f"skills={len(result.skills)} "
                f"tools={len(result.tools)}"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[ResumeParser] JSON parse failed after retries: {e}")
            raise

        except ValidationError as e:
            logger.error(f"[ResumeParser] Schema validation failed: {e}")
            raise
