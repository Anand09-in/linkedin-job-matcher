# Implementation Plan — v2

Status: Draft v1
Companion docs: [functional-requirements.md](functional-requirements.md), [architecture.md](architecture.md), [system-design.md](system-design.md), [flow-diagrams.md](flow-diagrams.md)

Scope: rebuild the LinkedIn Job Matcher as a fully Dockerized, single-user, local-first system with a single-step scrape→extract→filter→match pipeline, one selectable LLM for everything, and a React/TypeScript frontend — living in `v2/` alongside the current (v1) implementation until cutover.

Each phase has a goal, deliverables, and exit criteria — a phase isn't "done" until its exit criteria are checkable, not just "code written."

## Phase 0 — Foundations
**Goal:** a working, empty skeleton that proves the container topology before any real feature logic exists.

- Scaffold `v2/backend/` (module layout per architecture.md §3.1) and `v2/frontend/`.
- `docker-compose.yml` for v2: `api`, `worker`, `postgres`, `redis`, `frontend` — all networked, only `api` and `frontend` publish host ports (both `.env`-configurable, per FR-9.3).
- `core/config.py` (env-driven settings) and `core/llm.py` — port the single-LLM factory from v1's `config/llm_factory.py`, including the `ChatBedrockConverse` fix already validated in v1 (Mistral Large needs the Converse API, not raw `max_gen_len`-style invocation).
- Alembic wired to Postgres, one empty baseline migration.
- `GET /health` on the API returns DB and Redis connectivity.
- A trivial arq task (`ping_task`) proves worker ↔ Redis ↔ Postgres wiring end to end.

**Exit criteria:** `docker compose up` from a clean checkout brings up all 5 services with no host Python/Conda/browser install; `/health` is green; the trivial task completes and its result is visible in Postgres.

## Phase 1 — Domain model & persistence
**Goal:** the real schema exists and is exercised by a repository layer, independent of any scraping or LLM code yet.

- Implement `domain/models.py`: `Job`, `Resume`, `Pipeline`, `ScrapeRun`, `RejectedJob`, `LLMSetting` (architecture.md §3.2) — `Resume` has no `is_active` flag; `Pipeline.resume_id` is the only place a resume gets bound to anything (FR-1A).
- Implement `domain/repository.py`: async CRUD for resumes and pipelines (multi-row, not single-active), plus the filters/pagination/sort v1's `api/routes/jobs.py` already proved out — including a new `pipeline_id` filter — plus the bulk-delete-by-date + count-before pair (carry over directly — that feature already shipped and was verified in v1).
- Resume-deletion guard: deleting a `Resume` referenced by an enabled `Pipeline` is rejected at the repository layer (FR-1A.7), not left to the API layer to remember to check.
- Alembic migration for the full schema.
- Integration tests against a real (containerized, ephemeral) Postgres, including: two pipelines bound to two different resumes coexist and are independently queryable/deletable.

**Exit criteria:** repository test suite green against Postgres in CI/local; `DELETE /jobs?before_date=` and `GET /jobs/count-before` ported and behaviorally identical to v1's (including the `date_posted`-empty fallback logic, now backed by a real `timestamptz` column instead of the free-text workaround it needed in v1) and composable with a `pipeline_id` filter; creating two resumes and two pipelines (one per resume) and listing jobs per `pipeline_id` works with no cross-contamination.

## Phase 2 — Universal scraper framework
**Goal:** jobs can be pulled from a real site in batches, with no LLM or filtering involved yet — proves the adapter interface is genuinely site-agnostic before a second adapter is attempted.

- `scrapers/base.py`: `BaseScraper` protocol, `RawJob` schema, batch-yielding contract (FR-1.1, FR-1.4).
- `scrapers/linkedin/adapter.py`: Playwright-based rewrite of v1's scraping logic — same query/filter surface (relevance, time window, employment type, experience level, locations), but owning the DOM selectors directly instead of depending on the 3rd-party `linkedin-jobs-scraper` library (system-design.md decision #3). This is also where the v1 `date_posted` extraction bug gets fixed properly, at the source.
- `scrapers/registry.py` mapping `site_name -> adapter class`.
- Worker task that runs an adapter against a `Pipeline` and writes raw batches to a temp queue/table (no persistence to `Job` yet — that's Phase 3).
- Fixture-based tests: adapter tested against saved HTML, not live LinkedIn (system-design.md §6).

**Exit criteria:** a manual scrape run against real LinkedIn produces correct raw batches of 5 with a populated `date_posted`; the adapter interface has no LinkedIn-specific leakage into `base.py`/`registry.py`, verified by writing one trivial second adapter (even a fake/test site) with zero changes to non-`linkedin/` code (FR-1.3, checked directly rather than assumed).

## Phase 3 — Batch extraction, deterministic filter, and save
**Goal:** the core single-step pipeline the whole redesign is about.

- `llm_tasks/schemas.py`: `JobAnalysisResult`, `BatchJobAnalysis`.
- `llm_tasks/batch_extract.py`: `analyze_batch()` — one structured-output call per batch of 5, returning extraction fields + match_score + matched/missing skills + rationale (FR-2.1, FR-2.2).
- `services/scrape_service.py`: orchestrates adapter → `analyze_batch(batch, pipeline.resume)` → deterministic threshold filter (pipeline's own override or system default, system-design.md §3.3) → upsert passing jobs tagged with `pipeline_id`/`scored_with_resume_id` → write `RejectedJob` rows (tagged `pipeline_id`) for the rest → update `ScrapeRun` counters.
- Batch-failure handling per system-design.md §1.1 (reject the batch, keep going, don't fail the run).
- LLM concurrency semaphore in `core/llm.py` per system-design.md §2.3 (sequential within one pipeline's run by default, shared cap across concurrently-running pipelines).
- Config surface: filter thresholds (min match score, max experience years) as `Pipeline` fields with a system-wide default fallback, not hardcoded (FR-1A.4).
- "Pipeline has no bound resume → extract-only mode" (FR-2.6) — a per-pipeline choice, not a global one.

**Exit criteria:** a real scrape run against LinkedIn, for a pipeline with a resume bound, produces `Job` rows with populated match scores and structured fields in one pass — no second "run matching" step exists or is needed. A deliberately-broken batch (mocked LLM failure) is confirmed not to abort the run. Running two pipelines back to back (e.g. "AI Engineer" then "Data Engineer," different resumes) produces jobs correctly tagged with their respective `pipeline_id`/`scored_with_resume_id`, with no bleed-through of one pipeline's resume into the other's scoring.

## Phase 4 — Parallel salary enrichment
**Goal:** salary lookups happen off the critical path, per FR-5.

- `services/salary_service.py`: web search (`ddgs`, carried over) + LLM synthesis using the single active LLM.
- `workers/tasks.py::salary_lookup_task`, idempotent by `job_id`, enqueued immediately on every successful save in Phase 3's save step.
- Retry policy for transient search/LLM failures; failure leaves `salary_enrichment_status` queryable, never blocks or rolls back the job save (FR-5.3).

**Exit criteria:** timing evidence (logs/timestamps) that job save and salary enrichment complete independently — a batch's next iteration is not observed waiting on a prior batch's salary tasks.

## Phase 5 — Single LLM selection, UI-driven
**Goal:** FR-3 in full — one model config, changeable at runtime, used everywhere.

- `LLMSetting` CRUD (`GET/PUT /settings/llm`), read by `core/llm.py` on every call site (extraction, salary synthesis, every feature) instead of env-only config.
- Remove the v1-style per-call `model`/`provider` override surface from feature endpoints (FR-3.1) — one active setting, no exceptions.
- Provider list carried over from v1's `llm_factory.py` (Bedrock, Anthropic, OpenAI, Groq, Gemini, Ollama), each still going through the corresponding LangChain chat class (including the `ChatBedrockConverse` fix from Phase 0).

**Exit criteria:** switching the active LLM via API (ahead of a real Settings UI existing) changes which provider both a new scrape run's extraction and an on-demand feature call use, with no container restart.

## Phase 6 — On-demand features
**Goal:** port v1's `features/` modules to the single-LLM model and per-job/per-click UX (FR-6).

- Port cover letter, ATS score, interview prep, company research/intel, resume improvement, career path — logic carries over largely as-is; the only structural change is removing per-call model overrides (now implicit via Phase 5's active setting) and adding the result cache keyed by `(job_id, resume_id, feature)` (FR-6.3).
- `POST /features/{feature}/{job_id}` endpoints, synchronous (system-design.md §"On-demand features" — deliberately not queued).

**Exit criteria:** each ported feature produces output for a real job/resume pair and is served from cache on a second identical request without a new LLM call (verified via call count, not just response shape).

## Phase 7 — API surface completion
**Goal:** everything the frontend will need exists and is documented via OpenAPI before frontend work starts, so codegen (Phase 8) has a real contract to work from.

- Finalize `jobs`, `scrape`, `resume`, `settings`, `features` routers per architecture.md §3.4.
- Export/CSV/Excel endpoints ported from v1.
- OpenAPI schema reviewed for completeness — every response model has no bare `dict` returns left over from quick Phase 0–6 prototyping.

**Exit criteria:** `openapi.json` is stable enough that regenerating the frontend client twice in a row produces no diff for unrelated endpoints.

## Phase 8 — Frontend rebuild (React + TypeScript)
**Goal:** FR-8 in full, feature-parity with v1's Streamlit UI at minimum.

- Vite + React + TS scaffold; Tailwind + shadcn/ui; TanStack Query + Zustand; React Router.
- Generated API client from Phase 7's `openapi.json`.
- Pages: Job Results (filter/sort/paginate, bulk delete by date, **filter by pipeline**), Job Detail (score breakdown, on-demand feature triggers with loading/cached states), Resume library (upload/list/delete multiple resumes, each named), Pipelines manager (create/edit pipelines — name, bound resume, site, query, locations, filters, batch size, threshold overrides, enable/disable, schedule) + per-pipeline run status/history, Tracker, Settings (global LLM selection only — the UI surface for Phase 5's backend capability).
- Dockerized: Vite dev server container for dev, Nginx-served static build for prod (FR-9.2).

**Exit criteria:** every v1 Streamlit page has a v2 equivalent reachable and functional end-to-end against the real backend (not mocked), confirmed by walking through each page manually against a live `docker compose up` stack.

## Phase 9 — Hardening, migration, cutover
**Goal:** v2 is trustworthy enough to replace v1.

- Optional one-time data migration script: v1 SQLite → v2 Postgres (preserve job history/tracker status if the user wants continuity rather than a clean slate — confirm this preference before building it, don't assume).
- Structured logging + per-run/per-batch metrics surfaced via the API (system-design.md §6 testing strategy validated end-to-end: adapter fixtures, mocked-LLM filter tests, Postgres integration tests, frontend component tests all green).
- `.env.example` covering every secret/config the full compose stack needs.
- Soak test: one real multi-hour scrape run (multiple batches, real throttling conditions) to validate system-design.md §2's concurrency assumptions against actual provider behavior, not just theory.
- Retire/archive v1 code once the user confirms v2 covers their real workflow (this is a user go/no-go, not an automatic step).

**Exit criteria:** user has run their actual job search workflow on v2 for a real session and explicitly signs off on cutover.

## Sequencing notes

- Phases 0–4 are strictly sequential (each depends on the previous phase's real output, not a stub) — this is the core pipeline and is the highest-risk, highest-value part of the rebuild; get it right before touching the frontend.
- Phase 5 (single LLM) is placed after the core pipeline works with *a* hardcoded LLM path, so "make it swappable" doesn't get tangled with "make it work" — a deliberate ordering choice, not an oversight.
- Phases 6–7 can partially overlap (porting a feature and wiring its route are naturally done together per feature).
- Phase 8 (frontend) intentionally starts only after Phase 7 freezes the API contract — building against a moving backend contract is exactly the kind of drift this redesign's OpenAPI-codegen decision (architecture.md §1) is meant to prevent.
