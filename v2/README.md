# LinkedIn Job Matcher — v2

Full redesign in progress. See [docs/plan.md](docs/plan.md) for the phase-by-phase
plan, and the other docs it links to ([functional-requirements.md](docs/functional-requirements.md),
[architecture.md](docs/architecture.md), [system-design.md](docs/system-design.md),
[flow-diagrams.md](docs/flow-diagrams.md)) for the full design.

**Status:** Phase 2 (Universal scraper framework) complete AND validated
against real, live LinkedIn (not just fixtures) — real jobs with full
descriptions were pulled successfully. `BaseScraper` + `RawJob`/`ScrapeConfig`
interface, a registry with zero site-specific mentions (mechanically checked
by a test), a real Playwright-based LinkedIn adapter that owns its DOM
selectors directly, and a trivial second ("testsite") adapter proving the
framework generalizes. No LLM extraction/filtering/matching yet, and nothing
is saved as a real `Job` yet — that's Phase 3. Job scraping/matching still
lives in the v1 code at the repo root until cutover.

LLM support is Bedrock-only by explicit decision (no Anthropic-direct/OpenAI/
Groq/Gemini/Ollama) — `core/llm.py` and `requirements.txt` were trimmed
accordingly.

**Lessons from live testing** (things a fixture can't catch, since they
involve LinkedIn's real async client-side rendering):
- LinkedIn lazily hydrates job-card content as it scrolls into view — reading
  fields before scrolling caught `date_posted` mid-hydration on most cards.
  Fixed: scroll into view first, then read.
- The title element contains two newline-joined lines for the same job; the
  second is kept (matches how v1's third-party library already had to handle
  this).
- The description panel is persistent across job clicks — waiting for it to
  *exist* isn't enough, since it already exists from the previous job. Fixed
  to wait for its *content* to change.
- The same job gets different tracking query params (`trk=`, `trackingId=`,
  `refId=`) depending on which search-result page it appeared on — deduping
  on the raw URL would silently miscount the same job as several. Fixed by
  canonicalizing to just the `/jobs/view/<id>/` path before any dedup logic
  sees it.
- A job-card click can occasionally trigger a full page navigation instead of
  an in-place panel update, breaking every subsequent locator on that page.
  Added recovery: detect it, re-open the current search results page, and
  continue rather than losing the rest of the batch.
- **Don't hit live LinkedIn repeatedly in quick succession while testing** —
  after ~3 scrape runs in a few minutes on one session, a run returned zero
  results for locations that had worked moments earlier, consistent with
  LinkedIn's own rate-limiting/anti-automation behavior kicking in. Space out
  manual test runs against the real site.

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

**Two test images, not one:** `api` deliberately does NOT have Playwright
installed (it's a ~300MB+ dependency only the `worker` image needs —
requirements-worker.txt / Dockerfile.worker). So:

```bash
# Repository + framework tests (fast, no Playwright needed):
docker compose run --rm --no-deps api pytest tests/test_repository.py tests/test_scraper_framework.py -v

# LinkedIn adapter tests (fixture-based, needs Playwright+Chromium):
docker compose run --rm --no-deps worker pytest tests/test_linkedin_adapter.py -v
```
One test (`test_two_independent_adapters_are_both_registered_with_no_special_casing`)
imports the real LinkedIn adapter to prove cross-adapter registration — it
`pytest.importorskip`s Playwright, so it skips (not fails) under `api` and
only actually runs under `worker`.

## Testing the LinkedIn adapter against real LinkedIn (Phase 2)

Everything except live-site interaction is verified by the fixture-based
tests above. To actually pull real jobs, set `LI_AT_COOKIE` in `.env`
(LinkedIn → DevTools → Application → Cookies → `li_at`), rebuild the worker
if you just added it (`docker compose build worker && docker compose up -d`),
then:

```bash
# 1. Create a pipeline (Phase 7 will replace this with a real POST /pipelines):
curl -X POST "http://localhost:8000/debug/quick-pipeline?name=Test&query=AI+Engineer&locations=Bangalore,+India"
# -> {"pipeline_id": "...", ...}

# 2. Trigger a scrape (runs in the worker container, hits real LinkedIn):
curl -X POST "http://localhost:8000/debug/scrape-preview?pipeline_id=<id from step 1>"

# 3. Check what landed in Postgres — should show batches of 5 with
#    date_posted populated (the exact field that was silently empty for
#    every job in v1):
curl "http://localhost:8000/debug/scrape-preview-log?pipeline_id=<id from step 1>"
```
`docker compose logs worker` shows progress per batch. Without a cookie set,
step 2 fails fast and cleanly with `LI_AT_COOKIE is not set` — verified
during Phase 2 development — rather than hanging or failing obscurely deep
inside a Playwright call.
