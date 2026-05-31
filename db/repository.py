"""
Database repository — all DB read/write operations in one place.

SyncJobRepository  → used by scraper + pipeline nodes (run in threads)
AsyncJobRepository → used by FastAPI routes

Phase 1 + Phase 3.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from db.models import Job, Resume, ScrapeRun

settings = get_settings()

# Sync engine for use inside background threads / pipeline nodes
_sync_url = settings.database_url.replace("+aiosqlite", "")
_sync_engine = create_engine(_sync_url, echo=False)
SyncSession = sessionmaker(bind=_sync_engine, expire_on_commit=False)


# ─────────────────────────────────────────────────────────────────────────────
# Sync repository
# ─────────────────────────────────────────────────────────────────────────────

class SyncJobRepository:

    def __init__(self, session: Session) -> None:
        self._s = session

    # ── ScrapeRun ─────────────────────────────────────────────────────────────

    def create_scrape_run(self, config_snapshot: dict) -> str:
        run = ScrapeRun(id=str(uuid.uuid4()), status="running",
                        config_snapshot=config_snapshot, jobs_found=0)
        self._s.add(run)
        self._s.commit()
        logger.info(f"[DB] ScrapeRun created: {run.id}")
        return run.id

    def finish_scrape_run(self, run_id: str, jobs_found: int, error: Optional[str] = None) -> None:
        status = "failed" if error else "completed"
        self._s.execute(
            update(ScrapeRun).where(ScrapeRun.id == run_id)
            .values(status=status, jobs_found=jobs_found,
                    finished_at=datetime.utcnow(), error=error)
        )
        self._s.commit()
        logger.info(f"[DB] ScrapeRun {run_id} → {status} ({jobs_found} jobs)")

    # ── Job upsert ────────────────────────────────────────────────────────────

    def upsert_job(self, job_data: dict) -> tuple[str, bool]:
        """Insert or update a job by unique link. Returns (job_id, is_new)."""
        link = job_data.get("link", "")
        if not link:
            return "", False

        existing = self._s.execute(
            select(Job).where(Job.link == link)
        ).scalar_one_or_none()

        if existing:
            existing.description = job_data.get("description") or existing.description
            existing.description_html = job_data.get("description_html") or existing.description_html
            existing.insights = job_data.get("insights") or existing.insights
            existing.apply_link = job_data.get("apply_link") or existing.apply_link
            existing.updated_at = datetime.utcnow()
            self._s.commit()
            return existing.id, False

        job = Job(
            id=str(uuid.uuid4()),
            title=job_data.get("title", ""),
            company=job_data.get("company", ""),
            location=job_data.get("location"),
            date_posted=job_data.get("date_posted"),
            link=link,
            apply_link=job_data.get("apply_link"),
            company_link=job_data.get("company_link"),
            description=job_data.get("description"),
            description_html=job_data.get("description_html"),
            insights=job_data.get("insights", []),
            status="new",
        )
        self._s.add(job)
        self._s.commit()
        return job.id, True

    def bulk_upsert_jobs(self, jobs: list[dict]) -> tuple[int, int]:
        new_count = updated_count = 0
        for job in jobs:
            _, is_new = self.upsert_job(job)
            if is_new:
                new_count += 1
            else:
                updated_count += 1
        logger.info(f"[DB] Upsert — {new_count} new, {updated_count} updated")
        return new_count, updated_count

    # ── Phase 3: parsed fields ────────────────────────────────────────────────

    def update_job_parsed_fields(self, job_id: str, enriched: dict) -> None:
        """Write JD parser output fields back to the Job row."""
        self._s.execute(
            update(Job).where(Job.id == job_id).values(
                skills_required=enriched.get("skills_required"),
                skills_nice_to_have=enriched.get("skills_nice_to_have"),
                experience_years=enriched.get("experience_years"),
                experience_years_min=enriched.get("experience_years_min"),
                seniority_level=enriched.get("seniority_level"),
                employment_type=enriched.get("employment_type"),
                remote_policy=enriched.get("remote_policy"),
                education_required=enriched.get("education_required"),
                salary_range=enriched.get("salary_range"),
                updated_at=datetime.utcnow(),
            )
        )
        self._s.commit()

    def batch_update_match_scores(self, scored_jobs: list[dict], resume_id: str = "") -> None:
        """Persist match_score, matched_skills, missing_skills, scored_with_resume_id."""
        for job in scored_jobs:
            job_id = job.get("id")
            if not job_id:
                continue
            self._s.execute(
                update(Job).where(Job.id == job_id).values(
                    match_score=job.get("match_score"),
                    matched_skills=job.get("matched_skills"),
                    missing_skills=job.get("missing_skills"),
                    scored_with_resume_id=resume_id or None,
                    updated_at=datetime.utcnow(),
                )
            )
        self._s.commit()
        logger.info(f"[DB] Match scores saved for {len(scored_jobs)} jobs")


# ─────────────────────────────────────────────────────────────────────────────
# Async repository  (FastAPI routes)
# ─────────────────────────────────────────────────────────────────────────────

class AsyncJobRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_scrape_run(self, run_id: str) -> Optional[ScrapeRun]:
        result = await self._s.execute(select(ScrapeRun).where(ScrapeRun.id == run_id))
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        min_score: Optional[float] = None,
        status: Optional[str] = None,
        company: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        q = select(Job)
        if min_score is not None:
            q = q.where(Job.match_score >= min_score)
        if status:
            q = q.where(Job.status == status)
        if company:
            q = q.where(Job.company.ilike(f"%{company}%"))
        q = (q.order_by(Job.match_score.desc().nullslast(), Job.scraped_at.desc())
               .limit(limit).offset(offset))
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_job(self, job_id: str) -> Optional[Job]:
        result = await self._s.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def update_job_status(self, job_id: str, status: str) -> bool:
        result = await self._s.execute(
            update(Job).where(Job.id == job_id).values(status=status)
        )
        await self._s.commit()
        return result.rowcount > 0

    async def save_resume(self, filename: str, raw_text: str) -> str:
        """Deactivate all previous resumes and save a new active one."""
        await self._s.execute(update(Resume).values(is_active=False))
        resume = Resume(id=str(uuid.uuid4()), filename=filename,
                        raw_text=raw_text, is_active=True)
        self._s.add(resume)
        await self._s.commit()
        return resume.id

    async def get_active_resume(self) -> Optional[Resume]:
        result = await self._s.execute(
            select(Resume).where(Resume.is_active == True)
        )
        return result.scalar_one_or_none()

    async def update_job_match(self, job_id: str, match_data: dict) -> None:
        await self._s.execute(
            update(Job).where(Job.id == job_id).values(
                match_score=match_data.get("score"),
                matched_skills=match_data.get("matched_skills"),
                missing_skills=match_data.get("missing_skills"),
                updated_at=datetime.utcnow(),
            )
        )
        await self._s.commit()
