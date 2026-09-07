# System Design Considerations — v2

Status: Draft v1
Companion docs: [functional-requirements.md](functional-requirements.md), [architecture.md](architecture.md), [flow-diagrams.md](flow-diagrams.md), [plan.md](plan.md)

This document exists to make trade-offs explicit and arguable, not to restate the architecture. Where v1's actual failures inform a decision, they're named directly — this project's own debugging sessions are the best available evidence of what breaks.

## 1. Reliability

### 1.1 A batch failure must not abort the run
v1's JD-parsing node already had the right instinct (per-job try/except, keep going, collect errors) but it ran one job at a time. In v2, the unit of failure is a batch of 5. If `analyze_batch()` raises after retries are exhausted:
- The batch's jobs are recorded as `jobs_rejected` with reason `"llm_batch_failed"`, not silently dropped and not retried forever.
- The scrape run continues to the next batch. A run's `status` is only `failed` if the *scraper adapter itself* fails (can't reach the site); LLM batch failures degrade the run's yield but don't fail it.
- Retry policy (tenacity, carried over from v1): exponential backoff, capped attempts, specifically catching provider throttling exceptions (v1 already had to work around Bedrock `ThrottlingException` by serializing calls — see §2.3 on concurrency for how v2 handles this more deliberately).

### 1.2 Idempotency
- Job upsert by `link` (carried over from v1) means re-scraping the same listing is always safe.
- Salary lookup tasks are idempotent by job id — a task that runs twice for the same job just overwrites `salary_benchmark` with the same or refreshed data. This matters because arq (like any task queue) gives at-least-once delivery, not exactly-once.
- Scrape run resumption: if the worker container restarts mid-run, the run is left in `status="running"` with no heartbeat. v2.1 accepts this as a known gap (single-user, manually re-triggered) rather than building run-resumption/heartbeat logic — see §5 Deferred.

### 1.3 The API must stay responsive during a scrape run
This is the direct fix for a v1 failure mode observed in this project's own debugging: a single FastAPI process doing scraping, LLM calls, and serving `/health` all on one event loop/thread pool meant a slow LLM call could stall everything else. v2's API/worker split (architecture.md §2) means `GET /jobs` and on-demand feature calls are served by a process that never runs Playwright or a multi-minute scrape loop.

## 2. Concurrency and throughput

### 2.1 Why batches of 5
Batching is primarily a **cost and latency** decision, not a correctness one: 5 job descriptions fit comfortably in one LLM context window for models in the Mistral-Large / Claude-Haiku class the project already uses, and one round trip for 5 jobs is meaningfully cheaper and faster than 5 round trips (fixed per-call overhead — auth, network, provider queuing — is paid once instead of five times). Batch size is a config value (`ScraperConfig.batch_size`), not hardcoded, so it can be tuned per model's practical context/quality limits.

### 2.2 Batch size trade-off
Larger batches (say, 20) would reduce LLM call count further but:
- increase the blast radius of a single failed call (more jobs re-queued or rejected together),
- risk quality degradation on structured-output extraction as the prompt grows (more items to track correctly in one response),
- increase latency-to-first-result (nothing is saved until the whole batch's response returns).

5 is the user-specified starting point; §5 flags batch-size tuning as something to revisit empirically once real latency/cost numbers exist, not something to over-design now.

### 2.3 LLM call concurrency
v1 discovered the hard way that Bedrock throttles concurrent calls (JD parsing was forced to `max_workers=1`). v2 keeps this constraint explicit rather than rediscovering it: the worker processes batches for a single pipeline's scrape run **sequentially** by default (one in-flight `analyze_batch()` call per run), with the batch's own tenacity retry/backoff absorbing transient throttling. Multiple pipelines running concurrently (FR-1A.5 — e.g. the "AI Engineer" and "Data Engineer" pipelines both scraping at once, each against their own resume) is the concrete, expected case this matters for, not a hypothetical: per-provider concurrency is capped via a shared semaphore in `core/llm.py` across *all* pipelines' runs — sized conservatively (e.g., 2) and made configurable, since the "safe" number is provider- and account-tier-specific and shouldn't be guessed permanently into the code. Two pipelines running concurrently means their batches interleave through that shared semaphore; it does not mean either pipeline runs faster or slower than running alone once the cap is hit — that's the trade-off of a shared credential/quota against N independent pipelines.

### 2.4 Salary enrichment runs in parallel, deliberately
Unlike batch extraction, salary lookups for different jobs are independent of each other and of the scrape loop — this is exactly the case the user called out as "parallel search... when saving to db." Each passing job enqueues its own `salary_lookup_task`; the worker's task queue naturally fans these out with its own concurrency limit (arq's `max_jobs`), separate from the LLM semaphore in §2.3 since salary lookups mostly wait on web search, not the same rate-limited LLM calls.

## 3. Data consistency

### 3.1 Filter-then-save is a one-time judgment, not a live view
FR-2.5/2.7 (functional-requirements.md) name this directly: a job's presence in the database reflects the resume its *pipeline* was bound to at scrape time — not a single global "active resume" (there isn't one — FR-1A.2). Editing a pipeline's `resume_id` after the fact does not retroactively re-score jobs that pipeline already produced; it only changes what future runs of that pipeline use. This is a deliberate scope cut, not an oversight — re-scoring a pipeline's full historical job set against a newly-bound resume is a different, larger feature (it needs the full JD text of jobs that were *rejected* and never fully stored, or a decision to always store full JDs regardless of filter outcome). If this becomes a real need, the fix is: store the raw JD (not the enriched fields) for all seen jobs regardless of filter outcome, and make "enrich + filter" a replayable operation against `PIPELINE.resume_id` — a schema-compatible extension, not a rewrite.

### 3.1a Multiple pipelines are independent, not variants of one config
A corollary worth stating plainly: the "AI Engineer" and "Data Engineer" pipelines (FR-1A.1) don't share filter thresholds, don't share a resume, and don't share `ScrapeRun`/`RejectedJob` history — each pipeline's rows are its own. The only things they share are infrastructure-level: the same Postgres instance, the same Redis queue, the same active `LLM_SETTING` (§ "Explicitly deferred" below notes per-pipeline LLM override is not in scope), and the same provider concurrency cap (§2.3). Deleting or disabling one pipeline has zero effect on another's data or runs.

### 3.2 What "reject" means, concretely
A rejected job is never a `Job` row — it's (optionally) a `RejectedJob` row: title/company/link/score/reason, enough to answer "why didn't I see this posting" without paying full storage or salary-enrichment cost for jobs the user explicitly doesn't want to see. `RejectedJob` retention is time-boxed (config, default 30 days) and cleaned up the same way the v1 bulk-delete-by-date feature already established the pattern for.

### 3.3 Deterministic filtering on top of a probabilistic score
The LLM produces `match_score` (FR-2.2); the system, not the LLM, decides pass/fail against a configured threshold (FR-2.4). This split matters for two reasons: it keeps the threshold adjustable without re-prompting or re-scraping, and it keeps "why was this job rejected" auditable as a number-vs-threshold comparison rather than an opaque LLM judgment call.

## 4. Security and configuration

- Secrets (LLM API keys, LinkedIn session cookie, AWS credentials) stay in `.env`, mounted into containers as environment variables — not committed, not baked into images. This is unchanged from v1's approach, which was already correct; v2 just applies it consistently across more containers (worker now also needs LLM credentials, previously only the API process did).
- `LLM_SETTING` (which provider/model is active) lives in Postgres and is safe to expose to the UI — it names a provider/model, it does not contain the credential itself. Credentials remain env-only; the DB row and the env var are separate concerns (which provider is *selected* vs. how that provider is *authenticated*).
- No new secrets class is introduced by the redesign; Postgres and Redis run without exposed credentials to the host beyond what Docker Compose's internal network requires (no host port publish needed for either in the default compose file — only `api` and `frontend` need host ports).

## 5. Explicitly deferred (do not design now)

Naming these here so they don't get silently re-litigated mid-implementation:
- Scrape run resumption / worker-crash recovery beyond "re-trigger manually."
- Multi-user auth (architecture.md §4 leaves the schema compatible, nothing more).
- Horizontal scaling / cloud deployment topology — this is a local Docker Compose project.
- Re-scoring historical jobs against a new resume (§3.1).
- Auto-tuning batch size — start at 5 as specified, revisit with real numbers after Phase 3 ships.
- Per-pipeline LLM override (e.g. a cheaper/faster model for one pipeline, a stronger one for another). FR-3.1 is explicit that there is one active LLM for everything; multiple pipelines share it. Revisit only if cost/quality needs are shown to genuinely diverge per pipeline.

## 6. Testing strategy

- **Scraper adapters**: tested against recorded HTML fixtures (Playwright can replay a saved page), not live LinkedIn — avoids tests that are flaky by construction and avoids hammering the real site in CI.
- **`analyze_batch`**: tested with the LLM call mocked to return a fixed `BatchJobAnalysis`, verifying the deterministic filter logic (§3.3) independently of any real model's behavior.
- **Repository/API layer**: standard integration tests against a real (containerized, ephemeral) Postgres — matches how v1's `tests/` already approached DB-backed testing, just on Postgres instead of SQLite.
- **Frontend**: component tests for the Job Results and Job Detail pages at minimum; the generated API client (architecture.md §1) removes an entire category of "does the client shape match the API" bugs that would otherwise need manual contract tests.

## 7. Decisions log

| # | Decision | Alternative considered | Why this way |
|---|---|---|---|
| 1 | Postgres over SQLite | Keep SQLite, add a file lock | SQLite's single-writer model directly conflicts with FR requiring API + worker + parallel salary tasks to write concurrently. |
| 2 | arq over Celery | Celery + RabbitMQ | Single-user local deployment doesn't need Celery's operational surface; arq is asyncio-native like FastAPI, one less paradigm to context-switch between. |
| 3 | Own Playwright adapters over `linkedin-jobs-scraper` | Keep the existing library, patch around its bugs | The library's DOM-selector bugs (the `date_posted` capture failure found in v1) are unfixable from our side except by forking it; owning the adapter is also a prerequisite for the "universal scraper" requirement, not an optional nicety. |
| 4 | Drop LangGraph for the core flow | Keep LangGraph, replace nodes | The new flow is a straight-line loop, not a multi-pass graph; a graph framework adds indirection without buying anything once there's no branching/parallel-fan-in to coordinate. |
| 5 | LLM decides score, code decides pass/fail | Let the LLM directly decide keep/reject | Keeps thresholds adjustable and rejections auditable without re-prompting (§3.3). |
| 6 | Rejected jobs get a lightweight audit row, not full storage | Store nothing / store everything | Nothing loses debuggability; everything defeats the point of filtering at scrape time and duplicates near-full job storage for jobs the user doesn't want. |
| 7 | Multiple resumes + multiple independent, resume-bound `Pipeline`s (no single "active resume") | Keep one active resume, require the user to switch it before each scrape | A user genuinely runs distinct searches in parallel (e.g. "AI Engineer" vs "Data Engineer"), each needing its own resume and its own query/filters, at the same time — a single active-resume toggle would force serializing searches that have no reason to be serial. |
| 8 | One global `LLM_SETTING`, not per-pipeline | Let each pipeline pick its own model | FR-3.1 is explicit: one model for everything is the whole point of removing v1's split between an embedding model and an LLM. Pipelines vary by resume/query/filters, not by which LLM processes them — kept out of scope unless a real cost/quality need emerges (§5). |
