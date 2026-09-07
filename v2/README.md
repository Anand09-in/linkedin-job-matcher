# LinkedIn Job Matcher — v2

Full redesign in progress. See [docs/plan.md](docs/plan.md) for the phase-by-phase
plan, and the other docs it links to ([functional-requirements.md](docs/functional-requirements.md),
[architecture.md](docs/architecture.md), [system-design.md](docs/system-design.md),
[flow-diagrams.md](docs/flow-diagrams.md)) for the full design.

**Status:** Phase 1 (Domain model & persistence) complete. Real schema —
`Resume`, `Pipeline`, `ScrapeRun`, `Job`, `RejectedJob`, `LLMSetting` — plus an
async repository with full CRUD, filtering/pagination/sort, bulk-delete-by-date,
and multi-resume/multi-pipeline isolation, all covered by a Postgres-backed
integration test suite. No scraping or LLM calls yet — that's Phase 2/3. Job
scraping/matching still lives in the v1 code at the repo root until cutover.

## Quickstart (Phase 0)

```bash
cp .env.example .env
# edit .env if you want a real LLM provider configured — not required for Phase 0

docker compose up --build
```

This brings up 5 services: `postgres`, `redis`, `migrate` (runs once and exits),
`api` (FastAPI, port 8000 by default), `worker` (arq), `frontend` (Vite dev
server, port 5173 by default). No host Python/Conda/browser install required
(FR-9.1) — the whole point of this phase is proving that.

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok","db":"ok","redis":"ok","version":"0.0.1"}

curl -X POST http://localhost:8000/debug/ping
# {"enqueued":true,"job_id":"..."}

curl http://localhost:8000/debug/ping-log
# [{"id":"...","message":"pong","created_at":"..."}]  <- proves worker -> redis -> postgres wiring
```

Then open http://localhost:5173 — the placeholder page calls `/health` itself.

If a port is already taken on your machine (a real problem hit during v1
development — an unrelated project's Docker container was found squatting on
port 8000), change `API_PORT`/`FRONTEND_PORT` in `.env` (FR-9.3).

`/debug/ping` and `/debug/ping-log` are Phase 0 scaffolding only — they get
removed once Phase 3 has a real scrape trigger to exercise the same wiring.

## Running the backend test suite (Phase 1+)

Postgres has no host-published port by design (see docker-compose.yml), so
tests run inside a container on the Compose network rather than from the host:

```bash
docker compose run --rm --no-deps api pytest -v
```

This spins up a dedicated `job_matcher_test` database (dropped/recreated fresh
each run), applies all Alembic migrations to it, and tears it down afterward —
your dev database (`job_matcher`) is never touched by tests.

**Gotcha to know about:** `migrate` and `api` share one Dockerfile and are
pinned to the same `image: v2_backend:local` tag in docker-compose.yml
specifically so they can't drift apart. If you ever add a service that copies
that Dockerfile instead of reusing the tag, `docker compose build api` alone
will silently leave it stale — this bit Phase 1 development directly (a
rebuilt `api` image left `migrate` running old code, so `alembic upgrade head`
"succeeded" against a schema one migration behind). Prefer a bare
`docker compose build` (no service filter) when in doubt.
