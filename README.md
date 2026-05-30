# LinkedIn Job Matcher

An AI-powered job search assistant that scrapes LinkedIn, parses job descriptions,
matches them against your resume, and surfaces insights like skill gaps and interview prep.

## Stack
- **Scraper**: `linkedin-jobs-scraper` + Selenium
- **Pipeline**: LangGraph (multi-node agent graph)
- **Backend**: FastAPI + SQLite (via SQLAlchemy async)
- **UI**: Streamlit
- **LLM**: Model-agnostic via LangChain (Claude / Groq / GPT-4o / Ollama)

## Quick start

```bash
cp .env.example .env
# Fill in LI_AT_COOKIE and LLM keys in .env

pip install -r requirements.txt

# Start backend
uvicorn api.main:app --reload --port 8000

# Start UI (separate terminal)
streamlit run ui/app.py
```

## How to get your LI_AT_COOKIE
1. Log into LinkedIn in Chrome
2. Open DevTools → Application → Cookies → `https://www.linkedin.com`
3. Copy the value of the `li_at` cookie

## Phases
See `TASKS.md` for the full phase-by-phase task breakdown.
