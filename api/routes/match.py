"""
Resume upload and matching routes.

POST /resume              — upload PDF resume, extract + store text
POST /resume/{id}/parse   — (re)parse resume with LLM
GET  /resume/active       — get the currently active resume profile
POST /match               — run the full LangGraph pipeline
GET  /match/status        — get last match run summary

Phase 4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger

from api.dependencies import get_repo
from api.models import (
    MatchRequest, MatchResponse, JobResponse,
    ResumeUploadResponse, ResumeParseResponse, SkillGap,
)
from db.repository import AsyncJobRepository

router = APIRouter(tags=["Resume & Matching"])


# ── Resume upload ─────────────────────────────────────────────────────────────

@router.post("/resume", response_model=ResumeUploadResponse, status_code=201)
async def upload_resume(
    file: UploadFile = File(..., description="PDF resume file"),
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Upload a PDF resume.

    - Accepts only PDF files (validated by content type + extension).
    - Extracts raw text using pymupdf (fitz), falls back to pdfplumber.
    - Saves to DB as the active resume (previous resumes marked inactive).
    - Returns resume_id to use in POST /match.

    To also run LLM parsing, call POST /resume/{resume_id}/parse afterwards.
    """
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported. Please upload a .pdf file."
        )

    # Read bytes
    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(pdf_bytes) > 10 * 1024 * 1024:   # 10 MB cap
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")

    # Extract text
    from parser.resume_parser import ResumeParser
    extractor = ResumeParser.__new__(ResumeParser)
    raw_text = extractor.extract_text(pdf_bytes)

    if not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "No text could be extracted from this PDF. "
                "It may be a scanned image. Please use a text-based PDF."
            )
        )

    # Save to DB (marks previous resume inactive)
    resume_id = await repo.save_resume(file.filename, raw_text)
    logger.info(
        f"[POST /resume] Saved resume '{file.filename}' "
        f"({len(raw_text):,} chars) → id={resume_id}"
    )

    return ResumeUploadResponse(
        resume_id=resume_id,
        filename=file.filename,
        characters_extracted=len(raw_text),
        preview=raw_text[:200].strip(),
        message=(
            f"Resume uploaded successfully. "
            f"Call POST /resume/{resume_id}/parse to extract your profile with AI."
        ),
    )


@router.post("/resume/{resume_id}/parse", response_model=ResumeParseResponse)
async def parse_resume(
    resume_id: str,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Run LLM parsing on an uploaded resume.

    - Loads raw text from DB by resume_id.
    - Calls the configured LLM (Bedrock/Groq/etc.) to extract structured profile.
    - Caches the result in DB — subsequent calls use the cache.
    - Returns the full ParsedResume profile dict.
    """
    from sqlalchemy import select, update
    from db.models import Resume
    from config.llm_factory import get_llm
    from parser.resume_parser import ResumeParser

    # Load resume from DB
    result = await repo._s.execute(select(Resume).where(Resume.id == resume_id))
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail=f"Resume '{resume_id}' not found")

    # Use cached parse if available
    if resume.parsed_profile:
        logger.info(f"[POST /resume/{resume_id}/parse] Returning cached profile")
        return ResumeParseResponse(resume_id=resume_id, profile=resume.parsed_profile)

    # Parse with LLM
    try:
        llm = get_llm()
        parser = ResumeParser(llm=llm)
        parsed = parser.parse(resume.raw_text)
        profile = parsed.model_dump()
    except Exception as e:
        logger.error(f"[POST /resume/{resume_id}/parse] LLM parse failed: {e}")
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {str(e)}")

    # Save parsed profile back to DB
    await repo._s.execute(
        update(Resume).where(Resume.id == resume_id).values(parsed_profile=profile)
    )
    await repo._s.commit()
    logger.info(f"[POST /resume/{resume_id}/parse] Profile cached for {resume_id}")

    return ResumeParseResponse(resume_id=resume_id, profile=profile)


@router.get("/resume/active")
async def get_active_resume(repo: AsyncJobRepository = Depends(get_repo)):
    """
    Return the currently active resume's parsed profile.

    Returns 404 if no resume has been uploaded yet.
    """
    resume = await repo.get_active_resume()
    if not resume:
        raise HTTPException(
            status_code=404,
            detail="No resume found. Upload one at POST /resume."
        )
    return {
        "resume_id": resume.id,
        "filename": resume.filename,
        "uploaded_at": resume.uploaded_at,
        "has_parsed_profile": resume.parsed_profile is not None,
        "profile": resume.parsed_profile,
        "raw_text_preview": resume.raw_text[:300] if resume.raw_text else None,
    }


# ── Match ─────────────────────────────────────────────────────────────────────

@router.post("/match", response_model=MatchResponse)
async def run_matching(
    body: MatchRequest,
    repo: AsyncJobRepository = Depends(get_repo),
):
    """
    Run the full LangGraph matching pipeline.

    Flow:
        1. Load jobs from DB
        2. Parse unparsed job descriptions with LLM (cached after first run)
        3. Load + parse resume (cached after first run)
        4. Score every job against the resume (sentence-transformers + LLM fields)
        5. Compute skill gaps
        6. Persist all scores to DB
        7. Return ranked list of JobResponse

    This is a synchronous blocking call — it may take 1-5 minutes for large
    job sets (mostly LLM calls). Consider running in a background task for
    production use and polling a status endpoint.
    """
    import asyncio
    from pipeline.graph import run_pipeline

    # Resolve resume_id — use active if not supplied
    resume_id = body.resume_id or ""
    if not resume_id:
        resume = await repo.get_active_resume()
        if not resume:
            raise HTTPException(
                status_code=404,
                detail="No active resume found. Upload one at POST /resume first."
            )
        resume_id = resume.id

    logger.info(f"[POST /match] Starting pipeline for resume_id={resume_id}")

    # Run the blocking LangGraph pipeline in a thread pool
    # so we don't block FastAPI's event loop
    try:
        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(
            None,
            lambda: run_pipeline(resume_id=resume_id)
        )
    except Exception as e:
        logger.exception(f"[POST /match] Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=f"Matching pipeline failed: {str(e)}")

    scored_jobs = final_state.get("scored_jobs") or []
    skill_gaps  = final_state.get("skill_gaps") or []
    errors      = final_state.get("errors") or []

    # Convert to response models
    job_responses = [
        JobResponse(
            id=j.get("id", ""),
            title=j.get("title", ""),
            company=j.get("company", ""),
            location=j.get("location"),
            date_posted=j.get("date_posted"),
            link=j.get("link", ""),
            apply_link=j.get("apply_link"),
            company_link=j.get("company_link"),
            description=j.get("description"),
            insights=j.get("insights"),
            skills_required=j.get("skills_required"),
            skills_nice_to_have=j.get("skills_nice_to_have"),
            experience_years=j.get("experience_years"),
            experience_years_min=j.get("experience_years_min"),
            seniority_level=j.get("seniority_level"),
            employment_type=j.get("employment_type"),
            remote_policy=j.get("remote_policy"),
            salary_range=j.get("salary_range"),
            match_score=j.get("match_score"),
            matched_skills=j.get("matched_skills"),
            missing_skills=j.get("missing_skills"),
            status=j.get("status", "new"),
            scraped_at=j.get("scraped_at"),
        )
        for j in scored_jobs
    ]

    gap_responses = [
        SkillGap(
            skill=g["skill"],
            frequency=g["frequency"],
            pct_jobs=g["pct_jobs"],
        )
        for g in skill_gaps
    ]

    logger.info(
        f"[POST /match] Done — "
        f"jobs={len(job_responses)} "
        f"gaps={len(gap_responses)} "
        f"errors={len(errors)}"
    )

    return MatchResponse(
        resume_id=resume_id,
        total_jobs=len(job_responses),
        scored_jobs=job_responses,
        skill_gaps=gap_responses,
        errors=errors,
    )
