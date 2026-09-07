"""
LinkedIn jobs-search URL construction.

Query param names and filter value codes ported from v1's `linkedin-jobs-
scraper` dependency (linkedin_scraper.py::__build_search_url + filters/
filters.py) — these are LinkedIn's own undocumented-but-stable query params,
not something to guess at; reusing the known-working values here is strictly
better than reinventing them.
"""
from __future__ import annotations

from urllib.parse import urlencode

JOBS_SEARCH_URL = "https://www.linkedin.com/jobs/search"

_RELEVANCE = {"RELEVANT": "R", "RECENT": "DD"}
_TIME = {"ANY": "", "DAY": "r86400", "WEEK": "r604800", "MONTH": "r2592000"}
_TYPE = {
    "FULL_TIME": "F", "PART_TIME": "P", "TEMPORARY": "T", "CONTRACT": "C",
    "INTERNSHIP": "I", "VOLUNTEER": "V", "OTHER": "O",
}
_EXPERIENCE = {
    "INTERNSHIP": "1", "ENTRY_LEVEL": "2", "ASSOCIATE": "3",
    "MID_SENIOR": "4", "DIRECTOR": "5", "EXECUTIVE": "6",
}
_REMOTE = {"ON_SITE": "1", "REMOTE": "2", "HYBRID": "3"}


def build_search_url(query: str, location: str, filters: dict, start: int = 0) -> str:
    """
    filters is the same shape as v1's config.yaml `filters:` block / v2's
    Pipeline.filters JSONB column, e.g.:
        {"relevance": "RECENT", "time": "WEEK", "type": ["FULL_TIME"],
         "experience": ["ENTRY_LEVEL", "ASSOCIATE"], "on_site_or_remote": ["REMOTE"]}
    Unrecognized keys/values are silently ignored rather than raising, so a
    pipeline with a typo'd filter degrades to "no filter" instead of failing
    the whole scrape run.
    """
    params: dict[str, str] = {}
    if query:
        params["keywords"] = query
    if location:
        params["location"] = location

    relevance = filters.get("relevance")
    if relevance in _RELEVANCE:
        params["sortBy"] = _RELEVANCE[relevance]

    time_filter = filters.get("time")
    if time_filter in _TIME:
        params["f_TPR"] = _TIME[time_filter]

    type_filters = [t for t in (filters.get("type") or []) if t in _TYPE]
    if type_filters:
        params["f_JT"] = ",".join(_TYPE[t] for t in type_filters)

    experience_filters = [e for e in (filters.get("experience") or []) if e in _EXPERIENCE]
    if experience_filters:
        params["f_E"] = ",".join(_EXPERIENCE[e] for e in experience_filters)

    remote_filters = [r for r in (filters.get("on_site_or_remote") or []) if r in _REMOTE]
    if remote_filters:
        params["f_WT"] = ",".join(_REMOTE[r] for r in remote_filters)

    params["start"] = str(start)
    return f"{JOBS_SEARCH_URL}?{urlencode(params)}"
