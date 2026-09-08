# Functional Requirements — v2

Status: Draft v1
Owner: architecture
Scope: single-user, local-first, fully Dockerized rebuild of the LinkedIn Job Matcher

## 1. Guiding intent

v1 scrapes first, stores raw jobs, then runs a separate LangGraph pipeline (JD parse → resume parse → embedding-based match) as a second pass, and uses two different "models" for that (a sentence-transformers embedding model for matching, an LLM for JD/resume parsing and for on-demand features). v2 collapses scraping, extraction, filtering, and matching into one step done immediately during scraping, using a single LLM selected from the UI for everything — extraction, matching, and on-demand features.

## 2. Actors

- **User** — the single local operator: configures scrape queries and filters, uploads a resume, picks the active LLM, browses results, triggers on-demand features, tracks applications.
- **Scheduler/System** — triggers scrape runs on a cron-like schedule (carried over from v1's `api/scheduler.py`) or on manual request.

## 3. Functional requirements by module

### FR-1 — Universal scraper framework
- FR-1.1: The system MUST define a scraper interface (`BaseScraper`) that any site adapter implements: given a query + filters, yield raw job postings (title, company, location, link, description, posted date if available, apply link).
- FR-1.2: LinkedIn MUST be the first implemented adapter, functionally equivalent to v1's coverage (search filters: relevance, time window, employment type, experience level, location).
- FR-1.3: Adding a new site adapter MUST NOT require changes to the batching, LLM-extraction, filtering, persistence, or worker orchestration code — only a new adapter module + registry entry.
- FR-1.4: The scraper MUST emit jobs in batches (default batch size 5, configurable) rather than one-at-a-time, so batches can be handed to the LLM extraction step as a unit.
- FR-1.5: Each scrape run MUST be tracked (id, status, started/finished timestamps, jobs_seen, jobs_saved, jobs_rejected, errors) — equivalent to v1's `ScrapeRun`.

### FR-1A — Multiple independent, resume-bound pipelines
- FR-1A.1: A **Pipeline** is a named, independently runnable configuration: one resume + one site adapter + one query/locations/filter set + its own batch size and (optionally) its own filter thresholds. Example: a "AI Engineer" pipeline bound to an AI-Engineer-focused resume and query, and a separate "Data Engineer" pipeline bound to a different resume and query — both defined and run independently.
- FR-1A.2: The system MUST support multiple resumes existing at once (no single global "active resume"). Each resume is independently uploadable, viewable, and assignable to one or more pipelines.
- FR-1A.3: The system MUST support multiple pipelines existing at once, each bound to exactly one resume (or none, per FR-2.6). Two pipelines MAY be bound to the same resume (e.g. same resume, two different location/query variants).
- FR-1A.4: A pipeline's filter thresholds (min match score, max experience years) MAY override the system default, so an "AI Engineer" pipeline and a "Data Engineer" pipeline can use different cutoffs if the user wants stricter/looser filtering per search.
- FR-1A.5: Pipelines MUST be runnable independently — triggering one pipeline's scrape MUST NOT block, cancel, or interfere with another pipeline's in-progress run. Running two pipelines concurrently against the same LLM provider MUST still respect the shared provider concurrency/rate-limit cap (system-design.md §2.3).
- FR-1A.6: Every saved `Job` and `RejectedJob` MUST record which pipeline produced it, so results are attributable and filterable by pipeline (and transitively by resume) in the UI — e.g. "show me only jobs from the Data Engineer pipeline."
- FR-1A.7: Deleting a resume that one or more enabled pipelines still reference MUST be prevented (or require explicitly disabling/reassigning those pipelines first) — never silently leave a pipeline pointing at a deleted resume.
- FR-1A.8: On-demand features (FR-6) for a given job MUST default to using the resume that job's pipeline was bound to (no separate "which resume" prompt needed for the common case), since that resume is already known via the job's pipeline.

### FR-2 — Single-step extraction, filtering, and matching
- FR-2.1: For each batch of raw jobs, the system MUST make one LLM call that returns, per job: structured fields (skills required/nice-to-have, experience years min/max, seniority, employment type, remote policy, education, salary hints) — equivalent to v1's JD parser output.
- FR-2.2: The same LLM call MUST also return a match assessment of each job against the resume bound to the pipeline being run (see FR-1A) — a match score (0–1), matched skills, missing skills, and a short rationale.
- FR-2.3: A job MUST only be persisted to the database if it passes the configured filter (min match score threshold AND max required experience years AND any other configured hard filters, all overridable per pipeline — FR-1A.4). Jobs that fail MUST NOT be silently lost from observability — the scrape run's `jobs_rejected` counter increments and (configurable) a lightweight rejection record (title, company, link, score, reason) is kept for a short retention window for debugging, without storing the full enriched job.
- FR-2.4: Filter thresholds MUST be deterministic, config/UI-driven values applied in code against the LLM's returned score/fields — the LLM does not unilaterally decide persistence; it scores, the system decides.
- FR-2.5: There MUST be no separate post-hoc "matching pipeline" run — extraction, filtering, and matching happen once, during scraping, against the one resume that pipeline is bound to.
- FR-2.6: A pipeline MAY be configured with no resume bound, running in "extract only, no filter" mode (config toggle), persisting jobs unscored — useful for a general market-scan pipeline that isn't tied to any one resume.
- FR-2.7: Re-scoring a job against a different resume after the fact is out of scope for v2.1 (documented as a known limitation — see system-design.md §Trade-offs). Re-running the same job posting through a *different pipeline* (different resume) is not the same thing and is fully supported — see FR-1A.5.

### FR-3 — Single unified LLM (Bedrock only), selectable from the UI
- FR-3.1: There MUST be exactly one active LLM configuration (model + temperature + max_tokens — provider is fixed to Bedrock, not user-selectable, per FR-3.3) used for extraction+filtering, and for every on-demand feature. No separate embedding model, no per-feature model override.
- FR-3.2: The active LLM MUST be changeable from the UI (Settings page) without editing `.env` or restarting containers, and MUST persist across restarts (stored in DB, not just env).
- FR-3.3: Amazon Bedrock is the ONLY supported provider (narrowed from v1's six-provider `llm_factory.py` by explicit decision — no Anthropic-direct, OpenAI, Groq, Gemini, or Ollama in v2). The UI lets the user pick a Bedrock *model* (e.g. Claude Haiku vs. Mistral Large), not a provider.
- FR-3.4: Changing the active LLM MUST NOT require re-running past scrapes; it only affects future extraction/matching/feature calls.

### FR-4 — Persistence
- FR-4.1: Jobs, once saved, MUST be deduplicated by canonical link (upsert semantics, carried over from v1).
- FR-4.2: The data store MUST support concurrent writers (API process + background workers) reliably — this rules out SQLite for v2 (see system-design.md).
- FR-4.3: Soft-delete (status=deleted) and hard bulk-delete-by-date (carried over from the v1 feature just built) MUST both be supported.
- FR-4.4: Schema changes MUST be managed through versioned migrations, not `create_all()`.

### FR-5 — Parallel salary enrichment on save
- FR-5.1: When a job is saved (passes the filter), a salary-lookup task MUST be dispatched asynchronously (not blocking the save or the next batch's scraping).
- FR-5.2: The salary task performs a web search (carried over: `ddgs`) + LLM synthesis (using the single active LLM) and writes the result back onto the job record once complete.
- FR-5.3: Salary enrichment failures MUST NOT fail or roll back the job save — the job exists with `salary_benchmark = null` until enrichment succeeds or is retried.
- FR-5.4: Salary tasks MUST be retryable and idempotent (safe to run twice for the same job).

### FR-6 — On-demand features (per job, on click)
- FR-6.1: The following features are triggered per-job, on user action, using the single active LLM: cover letter generation, interview prep, company research, resume improvement suggestions (carried over from v1's `features/`), plus referral outreach message drafting and salary negotiation prep (added when this phase was scoped — the former pairs with FR-6's existing referral-contact search, FR-1A.8-style, the latter reuses the salary benchmark FR-5 already computes per job). ATS score (a deterministic, non-LLM scorer) and career path were explicitly dropped, not carried over — a deliberate scope decision, not an oversight.
- FR-6.2: Each feature call MUST be synchronous from the UI's perspective (button click → loading state → result), consistent with today's UX — no polling/queue needed for these (they're single, user-initiated, one-off calls).
- FR-6.3: Feature results SHOULD be cached per (job, resume, feature, and any feature-specific params like a cover letter's tone or a referral message's addressee — two different params values are two different cache entries) so re-opening a previously generated result doesn't re-call the LLM, unless the user explicitly regenerates.

### FR-7 — Application tracking
- FR-7.1: Status tracking (new → saved → applied → interview → offer/rejected) and the tracker dashboard/stats are carried over unchanged in spirit from v1.

### FR-8 — Frontend
- FR-8.1: The UI MUST be rebuilt in React + TypeScript (replacing Streamlit), consuming the FastAPI backend over HTTP.
- FR-8.2: Feature parity with v1's pages is required at minimum, plus the new multi-pipeline model (FR-1A): Job Results (filter/sort/paginate + bulk delete by date + **filter by pipeline**), Job Detail (score breakdown, on-demand feature triggers), Resume library (upload/list/delete, multiple resumes), Pipelines manager (create/edit/enable/disable pipelines, each bound to a resume), run status/history per pipeline, Tracker, Settings (LLM selection — global, not per-pipeline).
- FR-8.3: The API client used by the frontend SHOULD be generated from the backend's OpenAPI schema rather than hand-written, to keep types in sync.

### FR-9 — Deployment
- FR-9.1: The entire backend (API, worker, database, cache/broker, browser automation) MUST run via `docker compose up` with no host-machine Python/Conda/browser-driver setup required — directly addressing the environment-drift issues found in v1 (missing deps, stray conda envs, port collisions with unrelated containers).
- FR-9.2: The frontend MUST also run containerized (dev: Vite dev server container; prod: static build served by Nginx container).
- FR-9.3: All service ports MUST be configurable via `.env` to avoid host port collisions (a concrete v1 pain point — port 8000 was found occupied by an unrelated project's container during this project's own debugging).

## 4. Non-functional requirements (summary — detailed in system-design.md)

- **Reliability**: a failed batch or a failed salary lookup must not abort the whole scrape run.
- **Observability**: every scrape run, batch, and LLM call is traceable via structured logs and per-run stats.
- **Cost/latency**: batching 5 jobs per LLM call is a deliberate cost/latency optimization over 1-job-per-call.
- **Extensibility**: new scraper sites and new on-demand features must be addable without touching core orchestration.
- **Portability**: no reliance on host-installed Python, Chrome, or conda environments.

## 5. Explicit out-of-scope for v2 phase 1

- Multi-user auth / multi-tenancy (deferred — see architecture.md §Future extension points).
- Re-scoring historical jobs against a newly uploaded resume.
- Horizontal scaling / cloud deployment topology (local Docker Compose only).
