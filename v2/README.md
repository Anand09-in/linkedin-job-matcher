# LinkedIn Job Matcher — v2

Full redesign in progress. See [docs/plan.md](docs/plan.md) for the phase-by-phase
plan, and the other docs it links to ([functional-requirements.md](docs/functional-requirements.md),
[architecture.md](docs/architecture.md), [system-design.md](docs/system-design.md),
[flow-diagrams.md](docs/flow-diagrams.md)) for the full design.

**Status:** Phase 0 (Foundations) — container topology only, no real domain
logic yet. Job scraping/matching still lives in the v1 code at the repo root.

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
