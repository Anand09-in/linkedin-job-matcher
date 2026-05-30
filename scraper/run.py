"""
Standalone scraper runner — use this to test Phase 1 manually.

Run from the project root:
    python -m scraper.run

Or with a custom query override:
    python -m scraper.run --query "Data Scientist" --limit 10
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from loguru import logger

# Add project root to path when running as script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LinkedIn Job Scraper — Phase 1 runner")
    parser.add_argument("--query", type=str, default=None, help="Override first query string")
    parser.add_argument("--limit", type=int, default=None, help="Override job limit")
    parser.add_argument("--location", type=str, default=None, help="Override first location")
    parser.add_argument("--dry-run", action="store_true", help="Print config only, don't scrape")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── Init DB tables ────────────────────────────────────────────────────────
    from db.database import init_db
    asyncio.run(init_db())
    logger.info("[INIT] Database tables ready")

    # ── Build service ─────────────────────────────────────────────────────────
    from scraper.service import ScraperService
    service = ScraperService()

    # Apply CLI overrides to first query config
    if args.query or args.limit or args.location:
        if service._query_cfgs:
            q = service._query_cfgs[0]
            if args.query:
                q["query"] = args.query
            if args.limit:
                q["limit"] = args.limit
            if args.location:
                q["locations"] = [args.location]
            logger.info(f"[OVERRIDE] Query → {q}")

    if args.dry_run:
        logger.info("[DRY RUN] Config:")
        logger.info(json.dumps(service._cfg, indent=2, default=str))
        logger.info("[DRY RUN] Queries that would be run:")
        for q in service._query_cfgs:
            logger.info(f"  • {q['query']} | {q.get('locations')} | limit={q.get('limit')}")
        return

    # ── Progress callback (prints live updates to terminal) ───────────────────
    def show_progress(job: dict, stats: dict) -> None:
        print(
            f"\r  [{stats['new']} new | {stats['updated']} updated | "
            f"{stats['errors']} errors]  Latest: {job['title']} @ {job['company']}",
            end="",
            flush=True,
        )

    service.on_progress = show_progress

    # ── Run ───────────────────────────────────────────────────────────────────
    logger.info("[START] Starting scrape run...")
    try:
        result = service.run_sync()
        print()  # newline after progress line
        logger.success(
            f"[DONE] run_id={result['run_id']} | "
            f"jobs={len(result['jobs'])} | "
            f"new={result['stats']['new']} | "
            f"updated={result['stats']['updated']} | "
            f"errors={result['stats']['errors']}"
        )

        # Print sample of first 3 jobs
        logger.info("[SAMPLE] First 3 jobs captured:")
        for job in result["jobs"][:3]:
            logger.info(
                f"  • {job['title']} @ {job['company']} ({job['location']})\n"
                f"    link: {job['link']}\n"
                f"    desc_length: {len(job.get('description') or '')}\n"
                f"    insights: {job.get('insights')}"
            )

    except ValueError as e:
        logger.error(f"[CONFIG ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"[FATAL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
