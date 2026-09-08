"""
Salary enrichment (FR-5) — web search + LLM synthesis, dispatched
asynchronously by salary_lookup_task whenever a job is saved (Phase 3's
scrape_service.py). Never blocks or fails a job save (FR-5.3).

Location- and experience-aware by construction: the search query includes
the job's location and experience level, not just its title — a generic
national-average salary figure isn't useful for comparison, which is
exactly the concern that shaped this (see system-design.md / plan.md
Phase 4 notes).
"""
from __future__ import annotations

from typing import Optional

from langchain_core.language_models import BaseChatModel

from app.llm_tasks.salary_synthesis import synthesize_salary
from app.llm_tasks.schemas import SalaryBenchmark
from app.services.web_search import format_snippets, web_search


def _build_query(job_title: str, company: str, location: Optional[str], experience_years_min: Optional[int]) -> str:
    parts = [job_title, company, "salary"]
    if location:
        parts.append(location.split(",")[0].strip())
    if experience_years_min is not None:
        parts.append(f"{experience_years_min}+ years experience")
    return " ".join(p for p in parts if p)


async def get_salary_benchmark(
    job_title: str,
    company: str,
    location: Optional[str],
    experience_years_min: Optional[int],
    llm: BaseChatModel,
) -> SalaryBenchmark:
    query = _build_query(job_title, company, location, experience_years_min)
    results = await web_search(query, max_results=6)
    snippets = format_snippets(results)
    return await synthesize_salary(job_title, company, location, experience_years_min, snippets, llm)
