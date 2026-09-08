"""
Async repository — all DB read/write operations in one place.

architecture.md §1 / decisions log: v1 needed separate Sync and Async
repositories because its scraper/pipeline ran in worker threads. v2's worker
is asyncio-native (arq), so ONE async repository serves both the API and the
worker — no thread-bound sync duplicate needed. This is a genuine
simplification over v1's db/repository.py, not just a rename.

Query-building for jobs (filters/sort/pagination) lives here rather than in
the API route, unlike v1's api/routes/jobs.py which built SQLAlchemy queries
directly in the route handler — keeping it in the repository is what makes
this layer independently testable against Postgres without an HTTP layer at
all (Phase 1's actual exit criterion).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, delete, func, nullslast, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import ResumeInUseError
from app.domain.models import FeatureResult, Job, LLMSetting, Pipeline, RejectedJob, Resume, ScraperCredential, ScrapeRun


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── Resume (FR-1A.2 — multiple, no "active" flag) ───────────────────────────

    async def create_resume(self, name: str, filename: str, raw_text: str) -> Resume:
        resume = Resume(name=name, filename=filename, raw_text=raw_text)
        self._s.add(resume)
        await self._s.commit()
        await self._s.refresh(resume)
        return resume

    async def list_resumes(self) -> list[Resume]:
        result = await self._s.execute(select(Resume).order_by(Resume.uploaded_at.desc()))
        return list(result.scalars().all())

    async def get_resume(self, resume_id: uuid.UUID) -> Optional[Resume]:
        return await self._s.get(Resume, resume_id)

    async def update_resume_parsed_profile(self, resume_id: uuid.UUID, profile: dict) -> None:
        await self._s.execute(update(Resume).where(Resume.id == resume_id).values(parsed_profile=profile))
        await self._s.commit()

    async def update_resume(
        self,
        resume_id: uuid.UUID,
        name: Optional[str] = None,
        filename: Optional[str] = None,
        raw_text: Optional[str] = None,
    ) -> Optional[Resume]:
        """Partial update for PUT /resumes/{id} (Phase 7) — a rename, or a
        replaced file, or both. Replacing raw_text clears parsed_profile: a
        cached ResumeProfile distilled from the OLD text would otherwise
        keep being reused by every pipeline bound to this resume, silently
        describing a candidate who no longer matches the uploaded PDF."""
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if filename is not None:
            fields["filename"] = filename
        if raw_text is not None:
            fields["raw_text"] = raw_text
            fields["parsed_profile"] = None
        if fields:
            await self._s.execute(update(Resume).where(Resume.id == resume_id).values(**fields))
            await self._s.commit()
        return await self.get_resume(resume_id)

    async def delete_resume(self, resume_id: uuid.UUID) -> bool:
        """FR-1A.7: refuse to delete a resume still bound to an ENABLED pipeline."""
        blocking = await self._s.execute(
            select(Pipeline.name).where(Pipeline.resume_id == resume_id, Pipeline.enabled.is_(True))
        )
        blocking_names = [row[0] for row in blocking.all()]
        if blocking_names:
            raise ResumeInUseError(resume_id, blocking_names)

        result = await self._s.execute(delete(Resume).where(Resume.id == resume_id))
        await self._s.commit()
        return result.rowcount > 0

    # ── Pipeline (FR-1A.1) ────────────────────────────────────────────────────

    async def create_pipeline(
        self,
        name: str,
        site: str,
        query: str,
        locations: Optional[list[str]] = None,
        filters: Optional[dict] = None,
        resume_id: Optional[uuid.UUID] = None,
        batch_size: int = 5,
        min_match_score_override: Optional[float] = None,
        max_experience_years_override: Optional[int] = None,
        enabled: bool = True,
        schedule_cron: Optional[str] = None,
    ) -> Pipeline:
        pipeline = Pipeline(
            name=name,
            site=site,
            query=query,
            locations=locations or [],
            filters=filters or {},
            resume_id=resume_id,
            batch_size=batch_size,
            min_match_score_override=min_match_score_override,
            max_experience_years_override=max_experience_years_override,
            enabled=enabled,
            schedule_cron=schedule_cron,
        )
        self._s.add(pipeline)
        await self._s.commit()
        await self._s.refresh(pipeline)
        return pipeline

    async def list_pipelines(self, enabled_only: bool = False) -> list[Pipeline]:
        q = select(Pipeline).order_by(Pipeline.created_at.desc())
        if enabled_only:
            q = q.where(Pipeline.enabled.is_(True))
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_pipeline(self, pipeline_id: uuid.UUID) -> Optional[Pipeline]:
        return await self._s.get(Pipeline, pipeline_id)

    async def update_pipeline(self, pipeline_id: uuid.UUID, **fields: Any) -> Optional[Pipeline]:
        """Partial update — only fields explicitly passed are touched."""
        if fields:
            await self._s.execute(update(Pipeline).where(Pipeline.id == pipeline_id).values(**fields))
            await self._s.commit()
        return await self.get_pipeline(pipeline_id)

    async def delete_pipeline(self, pipeline_id: uuid.UUID) -> bool:
        result = await self._s.execute(delete(Pipeline).where(Pipeline.id == pipeline_id))
        await self._s.commit()
        return result.rowcount > 0

    # ── ScrapeRun ─────────────────────────────────────────────────────────────

    async def create_scrape_run(self, pipeline_id: uuid.UUID, config_snapshot: dict) -> ScrapeRun:
        run = ScrapeRun(pipeline_id=pipeline_id, config_snapshot=config_snapshot, status="running")
        self._s.add(run)
        await self._s.commit()
        await self._s.refresh(run)
        return run

    async def get_scrape_run(self, run_id: uuid.UUID) -> Optional[ScrapeRun]:
        return await self._s.get(ScrapeRun, run_id)

    async def list_scrape_runs(self, pipeline_id: Optional[uuid.UUID] = None, limit: int = 20) -> list[ScrapeRun]:
        q = select(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit)
        if pipeline_id:
            q = q.where(ScrapeRun.pipeline_id == pipeline_id)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def delete_scrape_runs(self, pipeline_id: uuid.UUID) -> int:
        """Clears run history for a pipeline (Pipelines page "clear history"
        action). Never deletes a `running` row — even though the UI already
        disables this while a run is active, guarding here too means a
        stray/racing request can't pull the rug out from under
        scrape_service.py's own `update_scrape_run`/`finish_scrape_run`
        calls on a run it's still actively writing to. RejectedJob rows for
        the deleted runs cascade-delete with them (ondelete="CASCADE");
        Job.scrape_run_id on any jobs those runs produced is set to NULL
        (ondelete="SET NULL") — the jobs themselves are untouched, they just
        lose their "which run produced this" attribution."""
        result = await self._s.execute(
            delete(ScrapeRun).where(ScrapeRun.pipeline_id == pipeline_id, ScrapeRun.status != "running")
        )
        await self._s.commit()
        return result.rowcount or 0

    async def update_scrape_run(self, run_id: uuid.UUID, **fields: Any) -> Optional[ScrapeRun]:
        """Generic partial update — Phase 3 uses this for jobs_seen/saved/rejected counters."""
        if fields:
            await self._s.execute(update(ScrapeRun).where(ScrapeRun.id == run_id).values(**fields))
            await self._s.commit()
        return await self.get_scrape_run(run_id)

    async def finish_scrape_run(self, run_id: uuid.UUID, status: str = "completed") -> None:
        await self._s.execute(
            update(ScrapeRun)
            .where(ScrapeRun.id == run_id)
            .values(status=status, finished_at=datetime.now(timezone.utc))
        )
        await self._s.commit()

    async def request_scrape_run_cancellation(self, run_id: uuid.UUID) -> Optional[ScrapeRun]:
        """Only takes effect while the run is still `running` — a run that
        already finished (completed/failed/cancelled) has nothing left to
        stop. Returns None if the run doesn't exist or isn't running (the
        route treats either as "nothing to cancel"), otherwise the updated
        row. The scrape loop itself (scrape_service.py) is what actually
        notices this flag and stops — this just raises it."""
        run = await self.get_scrape_run(run_id)
        if run is None or run.status != "running":
            return None
        await self._s.execute(update(ScrapeRun).where(ScrapeRun.id == run_id).values(cancel_requested=True))
        await self._s.commit()
        return await self.get_scrape_run(run_id)

    # ── Job ───────────────────────────────────────────────────────────────────

    async def upsert_job(self, data: dict[str, Any]) -> tuple[Job, bool]:
        """Insert or update a Job by unique link (dedup, carried over from v1). Returns (job, is_new)."""
        link = data["link"]
        result = await self._s.execute(select(Job).where(Job.link == link))
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if key != "link":
                    setattr(existing, key, value)
            existing.updated_at = datetime.now(timezone.utc)
            await self._s.commit()
            await self._s.refresh(existing)
            return existing, False

        job = Job(**data)
        self._s.add(job)
        await self._s.commit()
        await self._s.refresh(job)
        return job, True

    async def get_job(self, job_id: uuid.UUID) -> Optional[Job]:
        return await self._s.get(Job, job_id)

    async def update_job_status(self, job_id: uuid.UUID, status: str) -> bool:
        result = await self._s.execute(
            update(Job).where(Job.id == job_id).values(status=status, updated_at=datetime.now(timezone.utc))
        )
        await self._s.commit()
        return result.rowcount > 0

    async def delete_job(self, job_id: uuid.UUID) -> bool:
        """Soft-delete — carried over from v1: hides from results, keeps the row
        so a future scrape of the same link doesn't resurface it silently."""
        return await self.update_job_status(job_id, "deleted")

    async def update_job_salary_benchmark(self, job_id: uuid.UUID, benchmark: dict, status: str = "done") -> None:
        """FR-5: called by salary_lookup_task once enrichment completes (or
        fails — status="failed" — see that task). Never touches match_score/
        status/anything else about the job, so a slow or failed salary
        lookup can't affect the job's visibility or filter outcome."""
        await self._s.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(salary_benchmark=benchmark, salary_enrichment_status=status, updated_at=datetime.now(timezone.utc))
        )
        await self._s.commit()

    async def list_jobs(
        self,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        min_experience: Optional[int] = None,
        max_experience: Optional[int] = None,
        company: Optional[str] = None,
        title: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        seniority: Optional[str] = None,
        remote_policy: Optional[str] = None,
        has_description: Optional[bool] = None,
        has_score: Optional[bool] = None,
        pipeline_id: Optional[uuid.UUID] = None,
        sort_by: str = "match_score",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Job]:
        """
        List jobs with the same filter/sort/pagination surface v1's
        api/routes/jobs.py proved out, plus pipeline_id (FR-1A.6).

        Deleted jobs are excluded unless status="deleted" is explicitly requested
        (identical semantics to v1).
        """
        q = select(Job)

        if status != "deleted":
            q = q.where(Job.status != "deleted")

        if min_score is not None:
            q = q.where(Job.match_score >= min_score)
        if max_score is not None:
            q = q.where(Job.match_score <= max_score)
        if min_experience is not None:
            q = q.where(Job.experience_years_min >= min_experience)
        if max_experience is not None:
            q = q.where(or_(Job.experience_years_min <= max_experience, Job.experience_years_min.is_(None)))
        if company:
            q = q.where(Job.company.ilike(f"%{company}%"))
        if title:
            q = q.where(Job.title.ilike(f"%{title}%"))
        if location:
            q = q.where(Job.location.ilike(f"%{location}%"))
        if status:
            q = q.where(Job.status == status)
        if seniority:
            q = q.where(Job.seniority_level == seniority)
        if remote_policy:
            q = q.where(Job.remote_policy == remote_policy)
        if has_description is True:
            q = q.where(Job.description.isnot(None))
        if has_description is False:
            q = q.where(Job.description.is_(None))
        if has_score is True:
            q = q.where(Job.match_score.isnot(None))
        if has_score is False:
            q = q.where(Job.match_score.is_(None))
        if pipeline_id is not None:
            q = q.where(Job.pipeline_id == pipeline_id)

        sort_map = {
            "match_score": nullslast(Job.match_score.desc()),
            "scraped_at": Job.scraped_at.desc(),
            "company": Job.company.asc(),
            "title": Job.title.asc(),
            "experience": nullslast(Job.experience_years_min.asc()),
        }
        sort_fields = [s.strip() for s in sort_by.split(",") if s.strip() in sort_map]
        order_clauses = [sort_map[f] for f in sort_fields] or [sort_map["match_score"]]
        q = q.order_by(*order_clauses).limit(limit).offset(offset)

        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_job_stats(self) -> dict:
        total = (await self._s.execute(select(func.count(Job.id)))).scalar() or 0
        with_desc = (
            await self._s.execute(select(func.count(Job.id)).where(Job.description.isnot(None)))
        ).scalar() or 0
        with_score = (
            await self._s.execute(select(func.count(Job.id)).where(Job.match_score.isnot(None)))
        ).scalar() or 0
        avg_score = (
            await self._s.execute(select(func.avg(Job.match_score)).where(Job.match_score.isnot(None)))
        ).scalar()
        return {
            "total_jobs": total,
            "with_description": with_desc,
            "with_match_score": with_score,
            "avg_match_score": round(float(avg_score), 3) if avg_score is not None else 0.0,
        }

    # ── Bulk delete by date (carried over from the v1 feature, now backed by a
    #    real timestamptz column instead of v1's free-text date_posted) ────────

    @staticmethod
    def _before_cutoff_clause(cutoff: date):
        """
        "Job is on/before cutoff" — prefers date_posted, falls back to
        scraped_at when date_posted is null (system-design.md §3, carried
        over from the v1 feature; the free-text substr workaround v1 needed
        is gone now that date_posted is a real timestamptz column).
        """
        return or_(
            and_(Job.date_posted.isnot(None), func.date(Job.date_posted) <= cutoff),
            and_(Job.date_posted.is_(None), func.date(Job.scraped_at) <= cutoff),
        )

    async def count_jobs_before(self, cutoff: date) -> int:
        result = await self._s.execute(select(func.count(Job.id)).where(self._before_cutoff_clause(cutoff)))
        return result.scalar() or 0

    async def delete_jobs_before(self, cutoff: date) -> int:
        result = await self._s.execute(delete(Job).where(self._before_cutoff_clause(cutoff)))
        await self._s.commit()
        return result.rowcount or 0

    # ── RejectedJob (FR-2.3) ──────────────────────────────────────────────────

    async def create_rejected_job(
        self,
        scrape_run_id: uuid.UUID,
        pipeline_id: uuid.UUID,
        title: str,
        company: str,
        link: str,
        reason: str,
        match_score: Optional[float] = None,
        experience_years_min: Optional[int] = None,
    ) -> RejectedJob:
        rejected = RejectedJob(
            scrape_run_id=scrape_run_id,
            pipeline_id=pipeline_id,
            title=title,
            company=company,
            link=link,
            match_score=match_score,
            experience_years_min=experience_years_min,
            reason=reason,
        )
        self._s.add(rejected)
        await self._s.commit()
        await self._s.refresh(rejected)
        return rejected

    async def list_rejected_jobs(
        self,
        pipeline_id: Optional[uuid.UUID] = None,
        scrape_run_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> list[RejectedJob]:
        q = select(RejectedJob).order_by(RejectedJob.created_at.desc()).limit(limit)
        if pipeline_id:
            q = q.where(RejectedJob.pipeline_id == pipeline_id)
        if scrape_run_id:
            q = q.where(RejectedJob.scrape_run_id == scrape_run_id)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def delete_rejected_jobs_older_than(self, days: int) -> int:
        """Retention cleanup — system-design.md §3.2 default 30-day window."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._s.execute(delete(RejectedJob).where(RejectedJob.created_at < cutoff))
        await self._s.commit()
        return result.rowcount or 0

    # ── LLMSetting — single active row, global (FR-3.1) ─────────────────────────

    async def get_active_llm_setting(self) -> Optional[LLMSetting]:
        result = await self._s.execute(select(LLMSetting).where(LLMSetting.is_active.is_(True)))
        return result.scalar_one_or_none()

    async def set_active_llm_setting(
        self, provider: str, model: str, temperature: float = 0.1, max_tokens: int = 2000
    ) -> LLMSetting:
        """There is always exactly one active row (FR-3.1) — update it in place
        if it exists, otherwise create it, rather than ever having more than one."""
        existing = await self.get_active_llm_setting()
        if existing:
            existing.provider = provider
            existing.model = model
            existing.temperature = temperature
            existing.max_tokens = max_tokens
            existing.updated_at = datetime.now(timezone.utc)
            await self._s.commit()
            await self._s.refresh(existing)
            return existing

        setting = LLMSetting(provider=provider, model=model, temperature=temperature, max_tokens=max_tokens)
        self._s.add(setting)
        await self._s.commit()
        await self._s.refresh(setting)
        return setting

    # ── FeatureResult — on-demand feature cache (FR-6.3) ─────────────────────────

    async def get_cached_feature_result(
        self, job_id: uuid.UUID, resume_id: Optional[uuid.UUID], feature: str, params_key: str
    ) -> Optional[FeatureResult]:
        """No DB-level uniqueness enforces this identity (see FeatureResult's
        docstring for why) — order by newest and take one, so a rare
        duplicate from a race condition just means "latest wins" instead of
        a crash on multiple rows."""
        q = (
            select(FeatureResult)
            .where(
                FeatureResult.job_id == job_id,
                FeatureResult.resume_id == resume_id,
                FeatureResult.feature == feature,
                FeatureResult.params_key == params_key,
            )
            .order_by(FeatureResult.created_at.desc())
            .limit(1)
        )
        result = await self._s.execute(q)
        return result.scalar_one_or_none()

    async def save_feature_result(
        self,
        job_id: uuid.UUID,
        resume_id: Optional[uuid.UUID],
        feature: str,
        params: dict,
        params_key: str,
        result: dict,
    ) -> FeatureResult:
        row = FeatureResult(
            job_id=job_id, resume_id=resume_id, feature=feature, params=params, params_key=params_key, result=result
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    # ── ScraperCredential — per-site session credential, UI-editable (Phase 8) ──

    async def get_scraper_credential(self, site: str) -> Optional[ScraperCredential]:
        result = await self._s.execute(select(ScraperCredential).where(ScraperCredential.site == site))
        return result.scalar_one_or_none()

    async def set_scraper_credential(self, site: str, value: str) -> ScraperCredential:
        """Upsert, like set_active_llm_setting — one row per site."""
        existing = await self.get_scraper_credential(site)
        if existing:
            existing.value = value
            existing.updated_at = datetime.now(timezone.utc)
            await self._s.commit()
            await self._s.refresh(existing)
            return existing

        credential = ScraperCredential(site=site, value=value)
        self._s.add(credential)
        await self._s.commit()
        await self._s.refresh(credential)
        return credential
