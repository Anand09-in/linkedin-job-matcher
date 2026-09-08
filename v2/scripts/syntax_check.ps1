<#
.SYNOPSIS
    Runs the arq worker natively on Windows, for LinkedIn scrape jobs only.

.DESCRIPTION
    2026-09-08 account-safety incident (see backend/app/scrapers/linkedin/
    adapter.py's module docstring and backend/app/core/config.py's
    linkedin_scrape_queue_name docstring for the full story): the Docker
    worker's Chrome (Linux container, minimal fonts, no GPU) got a real
    LinkedIn account restricted even after every in-container mitigation
    tried. A native process — real Chrome, real Windows fonts/platform
    fingerprint, run through the "jobs" conda env (the same one that ran
    v1's own scraper successfully) — proved reliable in a clean, controlled
    test where the container consistently wasn't.

    This worker listens ONLY on the dedicated linkedin_scrape_queue_name
    queue (routes/scrape.py enqueues run_scrape_task there specifically,
    never on arq's default queue), so it only ever picks up scrape jobs —
    the Docker worker keeps handling ping/salary lookups on the default
    queue, unaffected, whether or not this script is running.

    Requires:
      - The "jobs" conda env (conda env list) with this project's
        requirements-worker.txt packages installed into it (asyncpg/arq/
        alembic are the ones v1 didn't need — see this repo's memory notes
        for why conda env reuse over a fresh venv).
      - Postgres/Redis reachable on localhost — docker-compose.override.yml
        (gitignored, sits next to docker-compose.yml) publishes them; run
        `docker compose up -d postgres redis` first if they're not already up.
      - backend/.env present (copy of the repo-root v2/.env — this script
        copies it automatically if missing) with DATABASE_URL/REDIS_URL
        overridden below to point at localhost instead of the Docker
        service names.

.NOTES
    Runs in the foreground — keep this window open while you want scrape
    runs to actually process; stop with Ctrl+C. Meant to be started in its
    own terminal alongside `docker compose up`, not backgrounded.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$condaPython = "$env:USERPROFILE\anaconda3\envs\jobs\python.exe"

if (-not (Test-Path $condaPython)) {
    Write-Error "Conda env 'jobs' not found at $condaPython — see this script's header comment for what it needs."
    exit 1
}

$envFile = Join-Path $backendDir ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $repoRoot ".env") $envFile
    Write-Output "Copied $repoRoot\.env -> $envFile"
}

Push-Location $backendDir
try {
    $env:DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/job_matcher"
    $env:REDIS_URL = "redis://localhost:6379/0"
    $env:ARQ_QUEUE_NAME = "linkedin_native_queue"

    Write-Output "Starting native worker (jobs conda env) on queue '$env:ARQ_QUEUE_NAME'..."
    & $condaPython -m arq app.workers.worker_app.WorkerSettings
}
finally {
    Pop-Location
}

