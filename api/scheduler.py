"""
APScheduler — timestamp-persistent scheduler.

State is written to data/scheduler_state.json after every run so the
next_run time survives FastAPI restarts.  On startup the scheduler
calculates start_date from the last_ran_at timestamp instead of 'now',
so restarting the API never resets the countdown.

  last_ran_at + interval > now  →  resume normally at the scheduled time
  last_ran_at + interval ≤ now  →  missed run while down, catch up in 1 min
  never ran before              →  first run after one full interval
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_scheduler = None
_STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "scheduler_state.json"


# ── State persistence ─────────────────────────────────────────────────────────

def _load_state() -> dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "last_ran_at":   None,
        "last_status":   "never",
        "jobs_new":      0,
        "jobs_updated":  0,
        "error":         None,
    }


def _save_state(state: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"[Scheduler] Could not persist state: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current scheduler state for the /scrape/scheduler-status endpoint."""
    from config.settings import get_settings
    settings = get_settings()

    state = _load_state()

    next_run = None
    is_running = False
    if _scheduler and _scheduler.running:
        is_running = True
        job = _scheduler.get_job("auto_scrape")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()

    return {
        "enabled":        settings.scheduler_enabled,
        "running":        is_running,
        "interval_hours": settings.scheduler_interval_hours,
        "next_run":       next_run,
        "last_run": {
            "ran_at":       state.get("last_ran_at"),
            "status":       state.get("last_status", "never"),
            "jobs_new":     state.get("jobs_new", 0),
            "jobs_updated": state.get("jobs_updated", 0),
            "error":        state.get("error"),
        },
    }


async def start_scheduler() -> None:
    """Start the background scheduler if SCHEDULER_ENABLED=true."""
    from config.settings import get_settings
    settings = get_settings()

    if not settings.scheduler_enabled:
        logger.info("[Scheduler] Disabled (SCHEDULER_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning(
            "[Scheduler] apscheduler not installed — scheduler disabled. "
            "Run: pip install apscheduler"
        )
        return

    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")

    interval_hours = settings.scheduler_interval_hours
    now            = datetime.now(timezone.utc)
    state          = _load_state()
    last_ran_str   = state.get("last_ran_at")

    if last_ran_str:
        try:
            last_ran = datetime.fromisoformat(last_ran_str)
            if last_ran.tzinfo is None:
                last_ran = last_ran.replace(tzinfo=timezone.utc)

            next_due = last_ran + timedelta(hours=interval_hours)

            if next_due <= now:
                # Was down long enough that a run was missed — catch up in 1 min
                start_date = now + timedelta(minutes=1)
                logger.info(
                    f"[Scheduler] Missed run (was due {next_due.strftime('%d %b %H:%M')} UTC) "
                    f"— catch-up scrape in 1 minute"
                )
            else:
                # Resume where we left off
                start_date = next_due
                remaining = next_due - now
                h, m = divmod(int(remaining.total_seconds() / 60), 60)
                logger.info(
                    f"[Scheduler] Resuming from last run at {last_ran.strftime('%d %b %H:%M')} UTC "
                    f"— next scrape in {h}h {m}m"
                )
        except Exception as e:
            logger.warning(f"[Scheduler] Bad last_ran_at in state file ({e}) — defaulting to now + interval")
            start_date = now + timedelta(hours=interval_hours)
    else:
        # Never run before — wait one full interval before first run
        start_date = now + timedelta(hours=interval_hours)
        logger.info(
            f"[Scheduler] First start — initial scrape at {start_date.strftime('%d %b %H:%M')} UTC"
        )

    _scheduler.add_job(
        _run_scrape,
        trigger="interval",
        hours=interval_hours,
        start_date=start_date,
        id="auto_scrape",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,   # tolerate up to 1h late start
    )
    _scheduler.start()
    next_job = _scheduler.get_job("auto_scrape")
    logger.info(
        f"[Scheduler] Ready — every {interval_hours}h, "
        f"next run: {next_job.next_run_time.strftime('%d %b %H:%M')} UTC"
    )


async def stop_scheduler() -> None:
    """Gracefully stop the scheduler on shutdown."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")


# ── Scrape job ────────────────────────────────────────────────────────────────

async def _run_scrape() -> None:
    """Runs a full scrape in a thread so it doesn't block the event loop."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    state = _load_state()
    state["last_ran_at"] = datetime.now(timezone.utc).isoformat()
    state["last_status"] = "running"
    state["error"]       = None
    _save_state(state)
    logger.info("[Scheduler] Scheduled scrape starting…")

    try:
        from scraper.service import ScraperService
        service = ScraperService()
        loop    = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(
                pool,
                lambda: service.run_sync(config_snapshot={"trigger": "scheduler"}),
            )
        stats = result.get("stats", {})
        state.update({
            "last_status":  "success",
            "jobs_new":     stats.get("new", 0),
            "jobs_updated": stats.get("updated", 0),
            "error":        None,
        })
        _save_state(state)
        logger.info(
            f"[Scheduler] Done — new={stats.get('new',0)} updated={stats.get('updated',0)}"
        )
    except Exception as e:
        state.update({"last_status": "failed", "error": str(e)})
        _save_state(state)
        logger.exception(f"[Scheduler] Scrape failed: {e}")
