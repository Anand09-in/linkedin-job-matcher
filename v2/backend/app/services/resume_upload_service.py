"""
PDF text extraction for POST/PUT /resumes (Phase 7) — the real upload path
FR-1A.2 always meant, replacing the raw_text-only `/debug/quick-resume` used
for testing Phases 1-6.

Ported from v1's parser/resume_parser.py: pymupdf (fitz) first — fast,
handles the vast majority of resumes — falling back to pdfplumber for the
table-heavy/oddly-encoded PDFs pymupdf sometimes returns empty text for.
Kept as its own small module rather than folded into the route handler
since "PDF bytes -> clean text" is a pure function worth unit-testing
without spinning up FastAPI/Postgres.
"""
from __future__ import annotations

import re

from loguru import logger


class ResumeExtractionError(Exception):
    """Raised when neither extraction method could get any text out of the
    PDF (e.g. a scanned image with no text layer) — translated to HTTP 422
    by the resumes route."""


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract clean text from PDF bytes. Raises ResumeExtractionError if
    both pymupdf and pdfplumber come back empty (e.g. a scanned/image-only
    PDF with no text layer) — the caller (resumes route) turns this into a
    clear 422 rather than silently creating a Resume with empty raw_text
    that would go on to fail resume parsing much later, confusingly, during
    some later pipeline run."""
    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            pages = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        full_text = "\n".join(p for p in pages if p.strip()).strip()
        if full_text:
            logger.info(f"[resume_upload] extracted {len(full_text)} chars via pymupdf")
            return _clean_text(full_text)
    except Exception as e:
        logger.warning(f"[resume_upload] pymupdf failed: {e} — trying pdfplumber")

    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        full_text = "\n".join(pages).strip()
        if full_text:
            logger.info(f"[resume_upload] extracted {len(full_text)} chars via pdfplumber")
            return _clean_text(full_text)
    except Exception as e:
        logger.error(f"[resume_upload] pdfplumber also failed: {e}")

    raise ResumeExtractionError(
        "Could not extract any text from this PDF — it may be a scanned image with no text layer."
    )
