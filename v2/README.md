# LinkedIn Job Matcher — v2

Full redesign in progress. See [docs/plan.md](docs/plan.md) for the phase-by-phase
plan, and the other docs it links to ([functional-requirements.md](docs/functional-requirements.md),
[architecture.md](docs/architecture.md), [system-design.md](docs/system-design.md),
[flow-diagrams.md](docs/flow-diagrams.md)) for the full design.

**Status:** Phase 6 (On-demand features) complete: cover letter, interview
prep, company research, resume improvement, referral outreach message
drafting, and salary negotiation prep — all via one shared `POST
/features/{feature}/{job_id}`, one LLM call each, cached per (job, resume,
feature, params) so a repeat request doesn't re-call the LLM. See the Phase
6 section below for what changed from v1 and what was validated. Phase 5
(Single LLM selection, UI-driven) complete. `GET`/`PUT /settings/llm` (real,
non-debug endpoints) are the one place the active
Bedrock model/temperature/max_tokens are set; `core/llm.py::get_llm()` is
now async and reads that DB row on every call from every call site
(extraction, salary synthesis, referral synthesis) — no per-feature
model/provider override surface, no container restart needed to switch
models. Phase 4 (Parallel salary enrichment) complete, plus an extra
feature: on-demand referral-contact search. Every job saved by Phase 3's
pipeline now automatically triggers `salary_lookup_task` (web search + one
LLM call, fire-and-forget — never blocks scraping or affects a job's match
score/visibility if it fails). Referral-contact search is separate and
on-demand only — see the design-decision note below for why.

Phase 3 (Batch extraction, deterministic filter, and save) is complete: the
core single-step pipeline runs for real — scrape -> one structured-output
Bedrock call per batch (extraction + match assessment) -> deterministic
threshold filter -> save as a real `Job` row (or a lightweight `RejectedJob`
audit row if it doesn't pass). No separate "run matching" step exists —
`services/scrape_service.py` is the whole thing.

Phase 2 (Universal scraper framework) is complete and was validated against
real, live LinkedIn — see the "Lessons from live testing" section below.

Job scraping/matching still lives in the v1 code at the repo root until cutover.

LLM support is Bedrock-only by explicit decision (no Anthropic-direct/OpenAI/
Groq/Gemini/Ollama) — `core/llm.py` and `requirements.txt` were trimmed
accordingly.

**What Phase 3 validated:**
- 31 tests pass (repository, scraper framework, `analyze_batch` with a mocked
  LLM, and `scrape_service` integration tests against real Postgres with a
  fake scraper) — covering: a full run producing scored `Job` rows in one
  pass; a deliberately-broken batch not aborting the run; an adapter-level
  failure (can't reach the site) correctly marking the whole run failed,
  distinct from a batch-level LLM failure; two pipelines with different
  resumes not bleeding into each other; extract-only mode (no resume bound)
  saving everything unscored.
- **Verified against real Bedrock** (not mocked) with synthetic job data: the
  structured-output call works end to end, and extraction/match quality is
  genuinely good — a senior backend role with no AI/ML relevance was
  correctly scored 0.2 with an accurate rationale, while a well-matched AI
  Engineer role scored 0.95.
- **A real finding from that real Bedrock call**: Mistral Large occasionally
  returns more results than jobs in the batch (a malformed duplicate
  `job_index=0` followed by the correct one) — `scrape_service.py`'s
  reassembly already handles this correctly by construction (it's a dict
  keyed by `job_index`, so the later, correct entry wins), now locked in with
  an explicit test rather than left as an accidental side effect.
- A live end-to-end run (real LinkedIn + real Bedrock) was attempted but hit
  LinkedIn returning zero results for a query/location that worked minutes
  earlier — consistent with the rate-limiting noted below, not a code bug:
  the run correctly completed with 0/0/0 rather than crashing or hanging.

**Prompt-quality pass** (in response to real usage concerns — resume-aware
matching, experience-format consistency), also verified against real
Bedrock:
- `experience_years_min` is now explicitly normalized regardless of how a
  posting phrases it ("1+ years", "0-2 years", "minimum 2 yrs", "entry
  level" all map to a plain integer) — needed for reliable filtering/sorting
  later, not just display. Verified live: "3-5 years" → `3`.
- The prompt now explicitly asks for recruiter-style reasoning about
  transferable/equivalent skills (resume says "TensorFlow", posting asks for
  "deep learning frameworks" → counts as a match), not literal string
  matching against the resume. Verified live.
- **A real bug this surfaced**: making the prompt richer pushed Mistral Large
  into occasionally generating runaway `skills_required` lists (280+ items,
  once degenerating into an unrelated thesaurus of adjectives) — a prose
  "keep it concise" instruction wasn't enough, and raising the token budget
  made it *worse* (more room for the runaway to run). Fixed at the schema
  level instead: `max_length=8` on every skill-list field (surfaced to the
  model as `maxItems` in its structured-output schema, a much stronger
  signal than prose) plus a defensive Pydantic validator that truncates
  regardless of what the model does — "the LLM scores, the system decides,"
  extended to "the LLM proposes skills, the system caps them." Verified live
  and locked in with 2 new unit tests.

**Resume-parsing (avoiding resending the full resume every batch call)**:
raised by a real efficiency question — LLM APIs are stateless per call, so
the resume must be in every batch's request regardless, but resending the
*full raw text* every time was avoidable. Added `resume_parser.py`: the LLM
distills a resume into a compact `ResumeProfile` (title, years, skills,
summary) **once**, cached in `Resume.parsed_profile`, then every batch call
for every pipeline bound to that resume reuses the cached profile instead of
the raw text. `scrape_service.py` resolves it once per run and treats a
parse failure as a run-level failure (same tier as an adapter failure), not
a silent fallback to unfiltered mode. Locked in with `test_resume_profile_is_parsed_once_and_cached`
(runs the same pipeline twice, confirms `parse_resume` is only invoked once).

- **A second real schema bug, found testing with the user's actual two
  resumes** (same person, one branded "Data Engineer," one "AI/ML Engineer,"
  both sharing an official "Software Development Engineer" title in their
  work history): asking the model to prefer the resume's self-branded title
  over the generic internal one caused it to dump the entire resume into the
  `current_title` field as a hedging run-on sentence, leaving every other
  field empty — twice, across two different prompt rewordings. The fix,
  again, was schema-level rather than more prose: moved every instruction
  into each field's own `Field(description=...)` (part of the actual tool
  definition, not just surrounding context) and reordered fields so the
  naturally verbose ones (`summary`, `skills`) come before the short
  categorical ones (`current_title`, `total_experience_years`), leaving
  nowhere earlier in the schema for overflow to spill into. Verified live
  against both real resumes: DE resume → `current_title: "Data Engineer"`,
  ML resume → `current_title: "AI/ML Engineer"`, both correctly overriding
  the shared "SDE" work-history title, both with accurate 1.5-year
  experience and well-curated skill lists.

**Phase 4 — salary enrichment + referral-contact search (design decisions and what was validated):**

- **Design decision on referral search, made explicitly with the user before
  building anything**: two structurally different features were considered —
  scraping LinkedIn's own People Search (richer data, but real automated
  scraping of member data, which LinkedIn's ToS treats far more seriously
  than job listings, and which would compound the rate-limiting risk already
  observed in Phase 2) vs. public web search for `site:linkedin.com/in`
  results (no li_at cookie, no LinkedIn automation at all, lower risk).
  Chosen: **web search only**. Also decided: **on-demand per job** (like
  cover letter/interview prep will be), not automatic for every saved job
  like salary — far lower request volume, and the user is unlikely to want
  referral contacts for every job a scrape run saves. `services/
  referral_service.py`'s module docstring records both decisions and why.
  Scope is explicitly surfacing-only — names/titles/profile links for the
  user to reach out to themselves; nothing here initiates any outreach.
- `services/web_search.py` — a shared DuckDuckGo (`ddgs`) wrapper used by
  both salary (automatic) and referral search (on-demand); fails soft
  (empty results, not an exception) since an external search dependency
  should never be able to take down either feature.
- Salary search is location- AND experience-aware by construction (a real
  usage concern raised directly): the query includes the job's location and
  experience level, not just its title, since a generic national-average
  figure isn't useful for comparison.
- **A third real schema bug from the same root cause, found via real
  Bedrock**: `SalaryBenchmark.currency` defaulted to `"USD"` and stayed
  there even for a Bangalore, India search — and `source_note` stayed empty
  despite an explicit prompt instruction to always explain the estimate.
  Same lesson as the two ResumeProfile bugs: a Pydantic field default
  becomes a `"default"` key in the JSON schema handed to the model, which
  reads as "this is fine unless told otherwise." Fixed by removing the
  defaults on `currency`/`confidence`/`source_note` (making them required)
  — verified live: a Bangalore search now correctly returns `currency:
  "INR"` with an honest "no direct 2-year figure found, confidence: low,
  amounts: null" rather than a wrong number; a US search for the same role
  returns `currency: "USD"` with a concrete, cited $160k-$180k range at
  `confidence: "medium"`.
- Referral search verified live against a real company (Zscaler): returned
  real named people with real profile URLs and relevance notes (e.g. "Senior
  Machine Learning Engineer at Zscaler, overlaps with data engineering"),
  correctly returning fewer/no results rather than fabricating contacts when
  the search didn't surface strong matches.
- `salary_lookup_task` is idempotent (safe to run twice) and a failure only
  marks `salary_enrichment_status="failed"` — it never touches a job's
  `match_score` or visibility (FR-5.3), verified with dedicated tests.

**Phase 5 — single LLM selection, UI-driven (what was validated):**

- `get_llm()` (`core/llm.py`) is now `async`: when a caller doesn't pass an
  explicit `model`/`temperature`/`max_tokens`, it opens a short-lived session
  and reads the one active `LLMSetting` row, falling back to the env-var
  default only if no row exists yet (first boot, before `PUT /settings/llm`
  has ever been called). An explicit arg (e.g. `scrape_service.py`'s larger
  batch-extraction `max_tokens`) always wins over the DB row — it's an
  override, not a default.
- All 4 call sites updated to `await get_llm(...)`: batch extraction
  (`scrape_service.py`), salary lookup (`workers/tasks.py`), and the
  referral-contacts endpoint (`main.py`); all corresponding test mocks
  switched from a plain `return_value=object()` patch to `AsyncMock`.
- **Verified live, end to end, exactly matching the plan's exit criterion**:
  `PUT /settings/llm` switched the active model from Mistral Large to Claude
  3 Haiku with the containers already running (no rebuild, no restart); the
  very next `/debug/referral-contacts` call failed with a Bedrock
  `AccessDeniedException` specific to Haiku (this AWS account's Marketplace
  subscription doesn't cover it) — itself proof the new model was actually
  used, since Mistral Large already works. Switching back to Mistral Large
  via the same endpoint, with no restart, made the identical call succeed
  again immediately.
- 64 tests pass (`docker compose exec worker pytest`) — rebuild the `api`/
  `worker`/`migrate` images first if you're validating this locally, since
  none of the three mount source as a live volume (`docker compose build
  migrate api worker && docker compose up -d migrate api worker`).

**Phase 6 — on-demand features (what changed from v1, and what was validated):**

- **Scope, decided explicitly by the user when this phase started**: ported
  cover letter, interview prep, company research, and resume improvement
  from v1's `features/`. ATS score (a deterministic, non-LLM keyword/section
  scorer in v1) and career path were dropped, not ported. Two features were
  added in their place instead: referral outreach message drafting (pairs
  with Phase 4's referral-contact search, which only ever surfaced names —
  never drafted anything to send) and salary negotiation prep (pairs with
  Phase 4's automatic salary enrichment, reusing the `salary_benchmark`
  already stored on the job rather than searching again).
- Every feature uses `.with_structured_output()` against its own schema
  (`llm_tasks/schemas.py`), not v1's per-module `json.loads` +
  regex-fence-stripping — removes a whole class of v1 silent-failure (a
  malformed response quietly degrading to an empty/placeholder result
  instead of a clear error).
- One shared entry point, `feature_service.run_feature()` — every route in
  `main.py` goes through it, so caching/resume-resolution can't be
  accidentally bypassed by a future call site. Resume context always comes
  from the job's own pipeline (FR-1A.8, no separate "which resume" choice);
  `company_research` is the one feature that doesn't need a resume at all,
  since it's about the employer/role, not candidate fit.
- **A real bug found live, the same root cause as three Phase 3/4 schema
  bugs before it**: `interview_prep`'s 12-question structured output is
  comparably large to a batch-extraction response, not a normal
  single-feature call — under the default token budget, Mistral Large
  truncated mid-item (a 9th question left with only its `category` field
  populated), which crashed the whole request with an uncaught Pydantic
  validation error. Fixed two ways: a dedicated
  `llm_interview_prep_max_tokens` setting (same pattern as
  `llm_batch_extract_max_tokens` from Phase 3), and a defensive
  `field_validator` that drops any malformed question item rather than
  raising — "the LLM proposes, the system decides," now extended to
  "...and discards what it botched," so one bad item can't take down 11 good
  ones. Verified live: a second attempt against the same job returned all
  12 well-formed, JD-specific questions.
- **Verified live against real Bedrock, end to end, for all 6 features**,
  against a real job/resume pair: `cover_letter` (confident tone,
  referencing the job's actual required skills and the resume's stated
  background), `company_research` (correctly flagged a deliberately sparse
  test JD as a red flag rather than inventing detail), `resume_improvement`,
  `referral_message` (personalized to a named contact), and
  `negotiation_prep` (grounded its talking points and target-ask range in
  the job's actual stored `salary_benchmark`, not a generic figure).
- **Cache verified live, not just in the mocked test suite**: the identical
  `cover_letter` request twice in a row returned `"cached": false` then
  `"cached": true` with byte-identical output; a different `tone` value
  produced a genuine second LLM call (FR-6.3 — params are part of the cache
  key, not just job/resume/feature).
- Error paths verified live: an unknown feature name and a nonexistent
  `job_id` both return HTTP 404; requesting a resume-requiring feature for a
  job whose pipeline had no resume bound (FR-2.6 extract-only mode) returns
  HTTP 422 with a clear message, while `company_research` on that same job
  succeeds normally.
- 80 tests pass — 64 from before Phase 6, plus 16 new (7 mocked-LLM unit
  tests, one per feature call, plus 2 for the `interview_prep` truncation
  fix, in `test_feature_llm_tasks.py`; 7 integration tests against real
  Postgres in `test_feature_service.py` covering cache hit/miss,
  `regenerate`, the resume-required error, and `company_research`'s
  no-resume path).

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
# Repository + framework + LLM/scrape-service tests (fast, no Playwright needed):
docker compose run --rm --no-deps api pytest tests/ --ignore=tests/test_linkedin_adapter.py -v

# LinkedIn adapter tests (fixture-based, needs Playwright+Chromium):
docker compose run --rm --no-deps worker pytest tests/test_linkedin_adapter.py -v
```
One test (`test_two_independent_adapters_are_both_registered_with_no_special_casing`)
imports the real LinkedIn adapter to prove cross-adapter registration — it
`pytest.importorskip`s Playwright, so it skips (not fails) under `api` and
only actually runs under `worker`.

## Testing the real pipeline end to end (Phase 3)

Everything except live-site interaction is verified by the tests above
(including a real, unmocked Bedrock call — see "What Phase 3 validated").
To run the actual scrape -> extract+match -> filter -> save pipeline against
real LinkedIn, set `LI_AT_COOKIE` in `.env` (LinkedIn → DevTools →
Application → Cookies → `li_at`) and make sure your Bedrock credentials are
set, rebuild if you just changed `.env`
(`docker compose build worker && docker compose up -d --force-recreate`),
then:

```bash
# 1. Create a resume (Phase 7 will replace this with real PDF upload):
curl -X POST http://localhost:8000/debug/quick-resume \
  -H "Content-Type: application/json" \
  -d '{"name": "My Resume", "raw_text": "..."}'
# -> {"resume_id": "...", ...}

# 2. Create a pipeline bound to that resume (Phase 7 replaces with real POST /pipelines).
#    `locations` is semicolon-separated (a single "City, Country" value already
#    has a comma in it — see the Phase 2 lesson above):
curl -X POST "http://localhost:8000/debug/quick-pipeline?name=Test&query=AI+Engineer&locations=Bangalore,+India&resume_id=<id from step 1>"
# -> {"pipeline_id": "...", ...}

# 3. Trigger a real run. `limit` keeps it small for manual testing — go easy
#    on LinkedIn's rate limits (see the lesson above):
curl -X POST "http://localhost:8000/debug/scrape?pipeline_id=<id from step 2>&limit=5"

# 4. Inspect what happened:
curl "http://localhost:8000/debug/scrape-runs?pipeline_id=<id from step 2>"   # status + counters
curl "http://localhost:8000/debug/jobs?pipeline_id=<id from step 2>"          # saved, scored jobs
curl "http://localhost:8000/debug/rejected-jobs?pipeline_id=<id from step 2>" # filtered-out jobs + why
```

`docker compose logs worker` shows progress. Omit `resume_id` in step 2 to
test FR-2.6's extract-only mode (every job saved, none filtered, all
unscored). Without `LI_AT_COOKIE` set, step 3 fails fast and cleanly with
`LI_AT_COOKIE is not set` rather than hanging.

## Testing salary enrichment + referral search (Phase 4)

Salary enrichment happens automatically — every job saved by step 3 above
already triggered `salary_lookup_task`; check the result via `/debug/jobs`
(now includes `salary_benchmark`/`salary_enrichment_status`) or re-run it
manually for one job:

```bash
curl -X POST "http://localhost:8000/debug/trigger-salary-lookup?job_id=<a job id from /debug/jobs>"
```

Referral-contact search is on-demand and synchronous — no job needed, works
with just a company/title (or pass `job_id` to look those up from a real job):

```bash
curl "http://localhost:8000/debug/referral-contacts?company=Zscaler&job_title=Data+Engineer"
```

Neither of these touches LinkedIn — both are web search (`ddgs`) + one
Bedrock call, so there's no rate-limit risk to the LinkedIn session from
testing these as much as you want.

## On-demand features (Phase 6)

One real (non-debug) endpoint for all 6 features — synchronous, cached per
(job, resume, feature, params):

```bash
curl -X POST "http://localhost:8000/features/cover_letter/<a job id from /debug/jobs>" \
  -H "Content-Type: application/json" -d '{"tone": "confident"}'

curl -X POST "http://localhost:8000/features/company_research/<job id>" -d '{}'   # no resume needed
curl -X POST "http://localhost:8000/features/interview_prep/<job id>" -d '{}'
curl -X POST "http://localhost:8000/features/resume_improvement/<job id>" -d '{}'

curl -X POST "http://localhost:8000/features/referral_message/<job id>" \
  -d '{"contact_name": "Jane Doe", "contact_title": "Senior AI Engineer"}'

curl -X POST "http://localhost:8000/features/negotiation_prep/<job id>" -d '{}'
```

Response shape: `{"feature", "job_id", "params", "cached", "result"}` —
`cached: true` means it was served from the `feature_results` table without
a new LLM call; pass `{"regenerate": true}` in the body to force a fresh
one. `job_id` must belong to a resume-bound pipeline for every feature
except `company_research` — otherwise the request fails with HTTP 422
(FR-2.6 extract-only pipelines have no resume to work from).

None of these touch LinkedIn — `cover_letter`/`interview_prep`/
`resume_improvement`/`negotiation_prep` use only what's already in Postgres
(the job's extracted fields + the resume's cached profile + `salary_benchmark`
for negotiation_prep), and `referral_message` just drafts text, it doesn't
search for the contact itself (`/debug/referral-contacts` does that).

## Changing the active LLM model (Phase 5)

```bash
curl http://localhost:8000/settings/llm
# {"provider":"bedrock","model":"mistral.mistral-large-3-675b-instruct","temperature":0.1,"max_tokens":2000}

curl -X PUT http://localhost:8000/settings/llm \
  -H "Content-Type: application/json" \
  -d '{"provider":"bedrock","model":"anthropic.claude-3-haiku-20240307-v1:0","temperature":0.1,"max_tokens":2000}'
```

Takes effect immediately, no restart — the next scrape run's extraction and
the next on-demand feature call both use the new model. `model` must be a
Bedrock model id your AWS account actually has Marketplace access to (see
the Phase 5 note above for what an access-denied model looks like).
