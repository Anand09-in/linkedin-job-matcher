# Task Board — LinkedIn Job Matcher

## Phase 1 — Foundation & Scraper Refactor
> Goal: working scraper that stores rich data to SQLite

- [ ] 1.1  Copy original `scraper.py` into `scraper/` for reference
- [ ] 1.2  Set `LI_AT_COOKIE` in `.env` (grab from browser DevTools)
- [ ] 1.3  Implement `ScraperService.run_sync()` — verify all EventData fields captured
- [ ] 1.4  Implement DB upsert in `_on_data` — dedup by `link` (unique constraint)
- [ ] 1.5  Create `ScrapeRun` record on start, update on end/error
- [ ] 1.6  Add multi-query loop from `config.yaml`
- [ ] 1.7  Test scraper against live LinkedIn (run manually, check SQLite)
- [ ] 1.8  Write `tests/test_scraper.py` with mock EventData

## Phase 2 — Parsers
> Goal: structured data extracted from raw text using LLM

- [ ] 2.1  Implement `ResumeParser.extract_text()` using pymupdf
- [ ] 2.2  Build LLM factory in `config/llm_factory.py` — swap provider via env var
- [ ] 2.3  Implement `ResumeParser.parse()` — prompt + structured JSON output
- [ ] 2.4  Implement `JDParser.parse()` — prompt + structured JSON output
- [ ] 2.5  Add retry logic (tenacity) for LLM calls
- [ ] 2.6  Add JSON schema validation on LLM responses (pydantic)
- [ ] 2.7  Test both parsers with sample PDF + sample JDs
- [ ] 2.8  Write `tests/test_parser.py`

## Phase 3 — LangGraph Pipeline
> Goal: end-to-end pipeline from raw jobs to scored matches

- [ ] 3.1  Define `PipelineState` (already done — review and adjust)
- [ ] 3.2  Implement `scraper_node` — calls ScraperService, writes raw_jobs
- [ ] 3.3  Implement `jd_parser_node` — batches JD parsing with concurrency
- [ ] 3.4  Implement `resume_parser_node` — loads resume from DB by resume_id
- [ ] 3.5  Implement `matcher_node` — sentence-transformers semantic similarity
- [ ] 3.6  Build `graph.py` — wire nodes with StateGraph, add conditional edges
- [ ] 3.7  Add parallel fan-out for feature nodes (Phase 6 prep)
- [ ] 3.8  Test graph with mock state, verify state transitions
- [ ] 3.9  Write `tests/test_pipeline.py`

## Phase 4 — FastAPI Backend
> Goal: REST API connecting all components

- [ ] 4.1  Implement `POST /scrape` — create ScrapeRun, enqueue in BackgroundTasks
- [ ] 4.2  Implement `GET /scrape/{run_id}` — poll scrape status
- [ ] 4.3  Implement `POST /resume` — PDF upload, text extraction, DB store
- [ ] 4.4  Implement `GET /jobs` — list with filters (score, status, company)
- [ ] 4.5  Implement `GET /jobs/{id}` — single job detail
- [ ] 4.6  Implement `POST /match` — invoke LangGraph pipeline
- [ ] 4.7  Implement `PATCH /jobs/{id}/status` — tracker status update
- [ ] 4.8  Add global exception handler + structured error responses
- [ ] 4.9  Add request logging middleware
- [ ] 4.10 Verify all endpoints with curl / Postman

## Phase 5 — Streamlit UI
> Goal: usable dashboard wired to the FastAPI backend

- [ ] 5.1  Build API client helper (`ui/api_client.py`) wrapping httpx calls
- [ ] 5.2  Implement Search & Scrape page — keyword input, location, filter toggles
- [ ] 5.3  Implement Job Results page — card grid, score badges, sort/filter sidebar
- [ ] 5.4  Implement `job_card` component — skills pills, score ring, apply button
- [ ] 5.5  Implement Resume Match page — PDF uploader, parsed profile preview
- [ ] 5.6  Implement `score_breakdown_chart` — plotly matched vs missing skills
- [ ] 5.7  Add real-time scrape progress bar (poll `/scrape/{run_id}`)
- [ ] 5.8  Add session state management (active resume, current filters)

## Phase 6 — Feature Modules
> Goal: advanced insights and tools on top of the core pipeline

- [ ] 6.1  Implement `cover_letter.py` — tailored cover letter via LLM
- [ ] 6.2  Implement `ats_scorer.py` — keyword density + ATS pass-rate prediction
- [ ] 6.3  Implement `skill_gap.py` — aggregate missing skills, rank by frequency
- [ ] 6.4  Implement `company_research.py` — fetch Glassdoor/web summary via LLM + search
- [ ] 6.5  Implement `interview_prep.py` — generate role-specific questions
- [ ] 6.6  Implement `salary_benchmark.py` — parse salary hints + market lookup
- [ ] 6.7  Implement Application Tracker Kanban UI (Streamlit drag-and-drop)
- [ ] 6.8  Wire all feature routes in FastAPI (`/features/*`)
- [ ] 6.9  Add feature nodes to LangGraph as parallel fan-out
- [ ] 6.10 Add Career Path Planner — suggest next roles based on skill gaps

## Phase 7 — Polish & Production
> Goal: stable, deployable, well-tested

- [ ] 7.1  Add `.env` validation on startup (raise if LI_AT_COOKIE missing)
- [ ] 7.2  Add rate-limit protection — exponential backoff on 429 errors
- [ ] 7.3  Add scheduled scraping (APScheduler or cron) — Phase 5 job alerts
- [ ] 7.4  Write comprehensive test suite (>70% coverage)
- [ ] 7.5  Add Docker + docker-compose (FastAPI + Streamlit services)
- [ ] 7.6  Add export — download matched jobs as CSV / Excel
- [ ] 7.7  Performance: cache embedding model, batch LLM calls
- [ ] 7.8  Write final README with screenshots and deployment guide
