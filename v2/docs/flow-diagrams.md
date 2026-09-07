# Flow Diagrams — v2

Status: Draft v1
Companion docs: [functional-requirements.md](functional-requirements.md), [architecture.md](architecture.md), [system-design.md](system-design.md), [plan.md](plan.md)

## 1. End-to-end scrape → extract → filter → save → enrich

```mermaid
flowchart TD
    A["Scrape triggered for Pipeline X<br/>(manual via UI, or pipeline's own schedule)"] --> B["Worker: load Pipeline X<br/>(its site, query, filters, thresholds, and bound Resume, if any)"]
    B --> C["Adapter.scrape() yields batch of 5 RawJob"]
    C --> D["analyze_batch(batch, pipeline.resume.raw_text, active_llm)<br/>ONE structured-output LLM call"]
    D --> E{LLM call<br/>succeeded?}
    E -- "no, retries exhausted" --> F["Mark all 5 as rejected<br/>reason=llm_batch_failed<br/>jobs_rejected += 5"]
    E -- yes --> G["For each of the 5 results:<br/>deterministic threshold check<br/>(pipeline's match_score / max_experience_years, override or default)"]
    G --> H{Passes<br/>filter?}
    H -- no --> I["Write RejectedJob<br/>(pipeline_id, title, company, link, score, reason)<br/>jobs_rejected += 1"]
    H -- yes --> J["Upsert Job row<br/>(pipeline_id, scored_with_resume_id, status=new)<br/>jobs_saved += 1"]
    J --> K["Enqueue salary_lookup_task(job_id)<br/>— fire and forget, non-blocking"]
    F --> L{More batches?}
    I --> L
    K --> L
    L -- yes --> C
    L -- no --> M["ScrapeRun.status = completed<br/>finished_at = now"]

    K -.async, separate worker slot.-> N["salary_lookup_task:<br/>web search (ddgs) + LLM synthesis"]
    N --> O["Update Job.salary_benchmark<br/>Job.salary_enrichment_status = done"]
```

Key property this diagram is meant to make obvious: **nothing about persistence blocks on salary enrichment**, and **one batch's LLM failure doesn't stop the loop** — both are direct responses to v1 pain points (a monolithic pipeline run that either fully succeeded or left partial state, and a single-process design where a slow call stalled everything). A second, independent instance of this exact diagram runs for Pipeline Y (e.g. "Data Engineer," its own resume, its own thresholds) with no coupling to Pipeline X beyond the shared LLM provider concurrency cap (system-design.md §2.3).

## 2. On-demand feature request (cover letter, interview prep, etc.)

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant FE as Frontend (React)
    participant API as API service
    participant DB as Postgres
    participant LLM as Active LLM provider

    U->>FE: click "Generate cover letter" on a job
    FE->>API: POST /features/cover-letter/{job_id}
    API->>DB: fetch Job + active Resume + cached result?
    alt cached result exists and not forced
        DB-->>API: cached cover letter
        API-->>FE: 200 {cover_letter, cached: true}
    else no cache / regenerate requested
        API->>DB: read active LLM_SETTING
        API->>LLM: single call, resume + job description
        LLM-->>API: generated text
        API->>DB: persist result keyed by (job_id, resume_id, feature)
        API-->>FE: 200 {cover_letter, cached: false}
    end
    FE-->>U: render result, loading state cleared
```

This stays synchronous by design (system-design.md is explicit that this is a deliberate choice, not an oversight): the user is actively waiting on one specific result for one job, so a request/response call with a client-side spinner is simpler than a queue+poll round trip and matches v1's existing UX.

## 3. Container / deployment view

```mermaid
flowchart LR
    subgraph Host["Developer machine"]
        subgraph Compose["docker compose up"]
            FE["frontend<br/>:5173 (dev) / :80 (prod)"]
            API["api<br/>:8000"]
            WRK["worker<br/>(no published port)"]
            RDS[("redis<br/>internal only")]
            PG[("postgres<br/>internal only, volume-backed")]
        end
    end

    Browser -- "http://localhost:5173 or :80" --> FE
    FE -- "http://localhost:8000 (or internal DNS in prod)" --> API
    API <-- "internal network" --> RDS
    API <-- "internal network" --> PG
    WRK <-- "internal network" --> RDS
    WRK <-- "internal network" --> PG
    WRK -- "outbound HTTPS" --> Internet["LLM provider / job sites / web search"]
    API -- "outbound HTTPS" --> Internet
```

Only `frontend` and `api` publish ports to the host; `postgres` and `redis` are reachable only inside the Compose network — closing off the class of problem this project hit directly during v1 debugging (an unrelated Docker container from a different project squatting on port 8000). Every port is `.env`-configurable per FR-9.3.

## 4. Data model relationships

See architecture.md §3.2 for the full ER diagram with fields. Relationship summary:

```mermaid
erDiagram
    RESUME ||--o{ PIPELINE : "bound to (0..1 per pipeline)"
    RESUME ||--o{ JOB : "scored_with (at scrape time)"
    PIPELINE ||--o{ SCRAPE_RUN : "runs of"
    PIPELINE ||--o{ JOB : produced
    SCRAPE_RUN ||--o{ JOB : produced
    SCRAPE_RUN ||--o{ REJECTED_JOB : produced
    LLM_SETTING ||--o{ JOB : "used for extraction+match (implicit, not FK, global not per-pipeline)"
```

`LLM_SETTING` is linked implicitly (which model produced a job's fields is knowable from timing/logs, not a hard FK) — adding a hard FK later is a compatible, non-breaking schema change if audit-grade "which model scored this" tracking is ever needed. Note the asymmetry: `RESUME`/`PIPELINE` are explicitly multi (a "AI Engineer" resume/pipeline and a "Data Engineer" resume/pipeline coexist independently), while `LLM_SETTING` is deliberately kept singular (decisions log #8, system-design.md) — the redesign's "one resume per search, one LLM for everything" split is a real asymmetry, not an inconsistency.
