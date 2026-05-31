"""
ScraperService — production-ready wrapper around linkedin_jobs_scraper.

Responsibilities:
  - Build Query objects from config.yaml dynamically
  - Capture ALL EventData fields (including description, insights, apply_link)
  - Upsert each job to SQLite via SyncJobRepository (dedup by link)
  - Track ScrapeRun lifecycle (created → running → completed/failed)
  - Thread-safe in-memory collection as fallback

Usage (standalone):
    python -m scraper.run

Usage (from FastAPI BackgroundTasks):
    service = ScraperService()
    run_id = service.start(background_tasks)
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Callable, Optional

from loguru import logger

from config.settings import get_settings
from db.repository import SyncJobRepository, SyncSession

# ── linkedin_jobs_scraper imports ─────────────────────────────────────────────
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import (
    RelevanceFilters,
    TimeFilters,
    TypeFilters,
    ExperienceLevelFilters,
    OnSiteOrRemoteFilters,
)

settings = get_settings()

# ── Filter string → enum maps ─────────────────────────────────────────────────
_RELEVANCE = {
    "RECENT": RelevanceFilters.RECENT,
    "RELEVANT": RelevanceFilters.RELEVANT,
}
_TIME = {
    "DAY": TimeFilters.DAY,
    "WEEK": TimeFilters.WEEK,
    "MONTH": TimeFilters.MONTH,
    "ANY": TimeFilters.ANY,
}
_TYPE = {
    "FULL_TIME": TypeFilters.FULL_TIME,
    "PART_TIME": TypeFilters.PART_TIME,
    "CONTRACT": TypeFilters.CONTRACT,
    "TEMPORARY": TypeFilters.TEMPORARY,
    "INTERNSHIP": TypeFilters.INTERNSHIP,
}
_EXPERIENCE = {
    "INTERNSHIP": ExperienceLevelFilters.INTERNSHIP,
    "ENTRY_LEVEL": ExperienceLevelFilters.ENTRY_LEVEL,
    "ASSOCIATE": ExperienceLevelFilters.ASSOCIATE,
    "MID_SENIOR": ExperienceLevelFilters.MID_SENIOR,
    "DIRECTOR": ExperienceLevelFilters.DIRECTOR,
    "EXECUTIVE": ExperienceLevelFilters.EXECUTIVE,
}
_REMOTE = {
    "ON_SITE": OnSiteOrRemoteFilters.ON_SITE,
    "REMOTE": OnSiteOrRemoteFilters.REMOTE,
    "HYBRID": OnSiteOrRemoteFilters.HYBRID,
}


# ─────────────────────────────────────────────────────────────────────────────

class ScraperService:
    """
    Configurable, class-based wrapper around LinkedinScraper.

    Thread safety:
        _collected and _stats are protected by _lock.
        run_sync() is blocking — call it from a thread or BackgroundTasks.
    """

    def __init__(self) -> None:
        self._cfg = settings.yaml_config
        self._scraper_cfg: dict = self._cfg.get("scraper", {})
        self._query_cfgs: list[dict] = self._cfg.get("queries", [])

        self._lock = threading.Lock()
        self._collected: list[dict] = []
        self._stats = {"new": 0, "updated": 0, "errors": 0}
        self._run_id: Optional[str] = None

        # Optional progress callback — called after each job is saved
        # Signature: (job_dict: dict, stats: dict) -> None
        self.on_progress: Optional[Callable[[dict, dict], None]] = None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _set_cookie(self) -> None:
        """Inject the LinkedIn session cookie into the environment."""
        cookie = settings.li_at_cookie
        if not cookie:
            raise ValueError(
                "LI_AT_COOKIE is not set.\n"
                "1. Log into LinkedIn in Chrome\n"
                "2. DevTools → Application → Cookies → linkedin.com → li_at\n"
                "3. Paste the value into your .env file"
            )
        os.environ["LI_AT_COOKIE"] = cookie

    def _build_queries(self) -> list[Query]:
        """Convert config.yaml query blocks into LinkedIn Query objects."""
        queries: list[Query] = []
        for qcfg in self._query_cfgs:
            f = qcfg.get("filters", {})

            # Build type filter list
            type_filters = [_TYPE[t] for t in f.get("type", []) if t in _TYPE] or None

            # Build experience filter list (optional)
            exp_filters = [_EXPERIENCE[e] for e in f.get("experience", []) if e in _EXPERIENCE] or None

            # Build remote filter list (optional)
            remote_filters = [_REMOTE[r] for r in f.get("on_site_or_remote", []) if r in _REMOTE] or None

            queries.append(
                Query(
                    query=qcfg["query"],
                    options=QueryOptions(
                        locations=qcfg.get("locations", []),
                        limit=qcfg.get("limit", 25),
                        apply_link=True,          # capture apply links (slower but richer)
                        skip_promoted_jobs=True,
                        filters=QueryFilters(
                            relevance=_RELEVANCE.get(f.get("relevance", "RECENT"), RelevanceFilters.RECENT),
                            time=_TIME.get(f.get("time", "MONTH"), TimeFilters.MONTH),
                            type=type_filters,
                            experience=exp_filters,
                            on_site_or_remote=remote_filters,
                        ),
                    ),
                )
            )
        logger.info(f"[SCRAPER] Built {len(queries)} query/queries from config")
        return queries

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_data(self, data: EventData) -> None:
        """
        Fired once per job. Extracts ALL available EventData fields and
        upserts immediately to SQLite so no data is lost on crash.
        """
        job = {
            "title": data.title,
            "company": data.company,
            "location": getattr(data, "place", None) or getattr(data, "location", None),
            "date_posted": data.date,
            "link": data.link,
            "apply_link": getattr(data, "apply_link", None),
            "company_link": getattr(data, "company_link", None),
            "description": data.description,
            "description_html": getattr(data, "description_html", None),
            # insights is a list: [seniority_level, employment_type, job_function, industry]
            "insights": list(data.insights) if getattr(data, "insights", None) else [],
        }

        # Thread-safe in-memory append (used for returning results)
        with self._lock:
            self._collected.append(job)

        # Immediate DB upsert per job
        try:
            with SyncSession() as session:
                repo = SyncJobRepository(session)
                _, is_new = repo.upsert_job(job)
                with self._lock:
                    if is_new:
                        self._stats["new"] += 1
                    else:
                        self._stats["updated"] += 1

            logger.info(
                f"[SCRAPED] {data.title} @ {data.company} | "
                f"desc={'yes' if job['description'] else 'no'} | "
                f"insights={len(job['insights'])}"
            )

            if self.on_progress:
                self.on_progress(job, dict(self._stats))

        except Exception as e:
            logger.error(f"[DB ERROR] Failed to upsert job '{data.title}': {e}")
            with self._lock:
                self._stats["errors"] += 1

    def _on_metrics(self, metrics: EventMetrics) -> None:
        logger.debug(f"[METRICS] {metrics}")

    def _on_error(self, error: Exception) -> None:
        logger.error(f"[SCRAPER ERROR] {error}")
        with self._lock:
            self._stats["errors"] += 1

    def _on_end(self) -> None:
        with self._lock:
            total = len(self._collected)
            stats = dict(self._stats)
        logger.info(
            f"[SCRAPER END] "
            f"total={total} | new={stats['new']} | "
            f"updated={stats['updated']} | errors={stats['errors']}"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run_sync(self, config_snapshot: Optional[dict] = None, run_id: Optional[str] = None) -> dict:
        """
        Blocking scrape run. Designed to be called from a thread.

        Args:
            config_snapshot: optional dict stored in ScrapeRun for auditing

        Returns:
            {
                "run_id": str,
                "jobs": list[dict],
                "stats": {"new": int, "updated": int, "errors": int},
            }
        """
        self._collected = []
        self._stats = {"new": 0, "updated": 0, "errors": 0}

        # ── 1. Validate cookie ────────────────────────────────────────────────
        self._set_cookie()

        # ── 2. Create ScrapeRun record (or reuse one created by the route) ──────
        snapshot = config_snapshot or self._cfg
        if run_id is None:
            with SyncSession() as session:
                repo = SyncJobRepository(session)
                run_id = repo.create_scrape_run(snapshot)
        self._run_id = run_id

        # ── 3. Build and run scraper ──────────────────────────────────────────
        try:
            from webdriver_manager.chrome import ChromeDriverManager

            scraper = LinkedinScraper(
                chrome_executable_path=ChromeDriverManager().install(),
                chrome_binary_location=None,
                chrome_options=None,
                headless=self._scraper_cfg.get("headless", True),
                max_workers=self._scraper_cfg.get("max_workers", 1),
                slow_mo=self._scraper_cfg.get("slow_mo", 1.5),
                page_load_timeout=self._scraper_cfg.get("page_load_timeout", 40),
            )

            scraper.on(Events.DATA, lambda data: self._on_data(data))
            scraper.on(Events.ERROR, lambda error: self._on_error(error))
            scraper.on(Events.END, lambda: self._on_end())
            scraper.on(Events.METRICS, lambda metrics: self._on_metrics(metrics))

            scraper.run(self._build_queries())

            # ── 4. Mark run completed ─────────────────────────────────────────
            with self._lock:
                total = len(self._collected)
                stats = dict(self._stats)

            with SyncSession() as session:
                repo = SyncJobRepository(session)
                repo.finish_scrape_run(run_id, jobs_found=total)

        except Exception as e:
            logger.exception(f"[SCRAPER] Fatal error: {e}")
            with SyncSession() as session:
                repo = SyncJobRepository(session)
                repo.finish_scrape_run(run_id, jobs_found=len(self._collected), error=str(e))
            raise

        with self._lock:
            return {
                "run_id": run_id,
                "jobs": list(self._collected),
                "stats": dict(self._stats),
            }
