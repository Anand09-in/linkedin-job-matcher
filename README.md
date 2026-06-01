# LinkedIn Job Matcher

> AI-powered job search — scrapes LinkedIn, matches against your resume, and generates cover letters, interview prep, salary research, and career planning.

[![LinkedIn Job Matcher — Full Demo](https://img.youtube.com/vi/mzmbP9_ZOow/maxresdefault.jpg)](https://youtu.be/mzmbP9_ZOow)

## Stack
`FastAPI` · `Streamlit` · `LangGraph` · `LangChain` · `sentence-transformers` · `SQLite`  
LLM-agnostic: Groq / Anthropic / OpenAI / Gemini / Ollama / AWS Bedrock

---

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in LI_AT_COOKIE + LLM key

uvicorn api.main:app --reload --port 8000   # terminal 1
streamlit run ui/app.py                      # terminal 2
```

UI → http://localhost:8501 · API docs → http://localhost:8000/docs

### Docker
```bash
docker-compose up --build
```

---

## Setup

### LinkedIn Cookie
1. Log in to LinkedIn → DevTools → **Application → Cookies**
2. Copy `li_at` value → set `LI_AT_COOKIE=` in `.env`

> Expires ~every 30 days.

### LLM Provider

| Provider | `.env` key | Notes |
|----------|-----------|-------|
| `groq` | `GROQ_API_KEY` | Free, fast — recommended |
| `anthropic` | `ANTHROPIC_API_KEY` | Claude |
| `openai` | `OPENAI_API_KEY` | GPT-4o |
| `gemini` | `GOOGLE_API_KEY` | Free tier |
| `bedrock` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | Claude/Llama on AWS |
| `ollama` | — | Local, set `OLLAMA_BASE_URL` |

The **✨ AI Features** sidebar lets you switch models per-session without touching `.env`.

---

## Workflow

**Search & Scrape → Resume & Match → Job Results → Skill Gaps → ✨ AI Features → Tracker**

### ✨ AI Features

| Tab | What it does |
|-----|-------------|
| ✉️ Cover Letter | Cliché-free 3-paragraph letter, cached per job |
| 📊 ATS Score | Instant keyword scan (no LLM): keyword density, title words, section headers, quantified achievements |
| 🎤 Interview Prep | 12 questions × 4 categories with answer frameworks |
| 🏢 Company & Salary | DuckDuckGo salary search + LLM company analysis |
| 📝 Resume Tips | Section rewrites, missing keywords, rewritten summary |

**Career Path Planner** — now / 6 months / 2 years horizons + learning roadmap.

### Export
Download from the **Job Results** page:  `⬇️ CSV` · `📊 Excel` (3 sheets: jobs, skill gaps, status board)

### Auto-Scrape
```env
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_HOURS=12
```

---

## Key `.env` Variables

```env
LI_AT_COOKIE=
LLM_PROVIDER=groq          # groq | anthropic | openai | gemini | bedrock | ollama
GROQ_API_KEY=              # fill whichever provider you use

# Optional
SCHEDULER_ENABLED=false
SCHEDULER_INTERVAL_HOURS=12
SCRAPER_BACKOFF_BASE=5.0   # seconds, for LinkedIn 429 backoff
```

Full list in `.env.example`.
