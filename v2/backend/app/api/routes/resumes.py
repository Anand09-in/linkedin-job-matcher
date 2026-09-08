"""
Resume routes (Phase 7, architecture.md §3.4 / FR-1A.2) — the real upload
path: a PDF file in, structured text out via resume_upload_service.py, no
`raw_text` typed in by hand like `/debug/quick-resume` needed for testing
Phases 1-6. FR-1A.7: DELETE is rejected with 409 if an enabled pipeline
still references the resume (Repository.delete_resume already enforces
this — this module just translates the exception to an HTTP status).
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.dependencies import get_repo
from app.api.models import ResumeDetailResponse, ResumeResponse
from app.domain.exceptions import ResumeInUseError
from app.domain.repository import Repository
from app.services.resume_upload_service import ResumeExtractionError, extract_pdf_text

router = APIRouter(prefix="/resumes", tags=["Resumes"])


def _extract_or_422(pdf_bytes: bytes) -> str:
    try:
        return extract_pdf_text(pdf_bytes)
    except ResumeExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("", response_model=ResumeDetailResponse, status_code=201)
async def create_resume(
    name: str = Form(...), file: UploadFile = File(...), repo: Repository = Depends(get_repo)
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    raw_text = _extract_or_422(await file.read())
    resume = await repo.create_resume(name=name, filename=file.filename, raw_text=raw_text)
    return ResumeDetailResponse.model_validate(resume)


@router.get("", response_model=list[ResumeResponse])
async def list_resumes(repo: Repository = Depends(get_repo)):
    return [ResumeResponse.model_validate(r) for r in await repo.list_resumes()]


@router.get("/{resume_id}", response_model=ResumeDetailResponse)
async def get_resume(resume_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    resume = await repo.get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    return ResumeDetailResponse.model_validate(resume)


@router.put("/{resume_id}", response_model=ResumeDetailResponse)
async def update_resume(
    resume_id: uuid.UUID,
    name: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    repo: Repository = Depends(get_repo),
):
    """Rename, replace the PDF, or both. Replacing the PDF re-extracts text
    and clears the cached ResumeProfile (Repository.update_resume) so the
    next pipeline run using this resume re-parses instead of scoring jobs
    against a stale profile."""
    existing = await repo.get_resume(resume_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    if name is None and file is None:
        raise HTTPException(status_code=400, detail="Provide at least one of name or file")

    raw_text = filename = None
    if file is not None:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        raw_text = _extract_or_422(await file.read())
        filename = file.filename

    updated = await repo.update_resume(resume_id, name=name, filename=filename, raw_text=raw_text)
    return ResumeDetailResponse.model_validate(updated)


@router.delete("/{resume_id}", status_code=204)
async def delete_resume(resume_id: uuid.UUID, repo: Repository = Depends(get_repo)):
    existing = await repo.get_resume(resume_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Resume {resume_id} not found")
    try:
        await repo.delete_resume(resume_id)
    except ResumeInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))
