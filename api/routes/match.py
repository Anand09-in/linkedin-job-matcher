"""
POST /match  — run resume-job matching pipeline
POST /resume — upload a PDF resume

Phase 4 implementation.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from api.models import MatchRequest, MatchResponse, ResumeUploadResponse
from db.database import get_db

router = APIRouter(tags=["matching"])


@router.post("/resume", response_model=ResumeUploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept a PDF resume, extract text, store in DB.
    TODO Phase 4: call ResumeParser.extract_text(), store Resume record.
    """
    raise NotImplementedError("Phase 4")


@router.post("/match", response_model=MatchResponse)
async def run_matching(body: MatchRequest, db: AsyncSession = Depends(get_db)):
    """
    Run the LangGraph pipeline for resume-job matching.
    TODO Phase 4: invoke pipeline graph, return scored jobs.
    """
    raise NotImplementedError("Phase 4")
