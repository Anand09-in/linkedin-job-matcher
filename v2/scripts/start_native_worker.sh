#!/usr/bin/env bash
# Runs the arq worker natively on Windows (via Git Bash), for LinkedIn scrape
# jobs only.
#
# 2026-09-08 account-safety incident (see backend/app/scrapers/linkedin/
# adapter.py's module docstring and backend/app/core/config.py's
# linkedin_scrape_queue_name docstring for the full story): the Docker
# worker's Chrome (Linux container, minimal fonts, no GPU) got a real
# LinkedIn account restricted even after every in-container mitigation
# tried. A native process -- real Chrome, real Windows fonts/platform
# fingerprint, run through the "jobs" conda env (the same one that ran v1's
# own scraper successfully) -- proved reliable in a clean, controlled test
# where the container consistently wasn't.
#
# This worker listens ONLY on the dedicated linkedin_scrape_queue_name queue
# (routes/scrape.py enqueues run_scrape_task there specifically, never on
# arq's default queue), so it only ever picks up scrape jobs -- the Docker
# worker keeps handling ping/salary lookups on the default queue, unaffected,
# whether or not this script is running.
#
# Requires:
#   - The "jobs" conda env (conda env list) with this project's
#     requirements-worker.txt packages installed into it (asyncpg/arq/
#     alembic are the ones v1 didn't need).
#   - Postgres/Redis reachable on localhost -- docker-compose.override.yml
#     (gitignored, sits next to docker-compose.yml) publishes them; run
#     `docker compose up -d postgres redis` first if they're not already up.
#   - backend/.env present (copy of the repo-root v2/.env -- this script
#     copies it automatically if missing) with DATABASE_URL/REDIS_URL
#     overridden below to point at localhost instead of the Docker service
#     names.
#
# Runs in the foreground -- keep this terminal open while you want scrape
# runs to actually process; stop with Ctrl+C. Meant to run in its own
# terminal alongside `docker compose up`, not backgrounded.
#
# Usage: ./scripts/start_native_worker.sh  (or: bash scripts/start_native_worker.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# ${VAR//\\//} replaces every backslash with a forward slash -- Windows'
# USERPROFILE comes as "C:\Users\name"; Git Bash needs "C:/Users/name" to
# invoke it directly rather than going through /c/... mount translation.
CONDA_PYTHON="${USERPROFILE//\\//}/anaconda3/envs/jobs/python.exe"

if [ ! -f "$CONDA_PYTHON" ]; then
    echo "Conda env jobs not found at $CONDA_PYTHON -- see the header comment in this script for what it needs." >&2
    exit 1
fi

ENV_FILE="$BACKEND_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$REPO_ROOT/.env" "$ENV_FILE"
    echo "Copied $REPO_ROOT/.env -> $ENV_FILE"
fi

cd "$BACKEND_DIR"
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/job_matcher"
export REDIS_URL="redis://localhost:6379/0"
export ARQ_QUEUE_NAME="linkedin_native_queue"

echo "Starting native worker (jobs conda env) on queue $ARQ_QUEUE_NAME..."
"$CONDA_PYTHON" -m arq app.workers.worker_app.WorkerSettings
