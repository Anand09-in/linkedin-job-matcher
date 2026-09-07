"""
Scraper registry — site_name -> adapter class (FR-1.3).

Pure mechanism only: this module must never name a specific site. Adapters
register themselves with @register("site_name") when their module is
imported; enumerating WHICH adapter modules to import is bootstrap.py's job,
not this one's — see that module's docstring for why the split matters.
"""
from __future__ import annotations

from app.scrapers.base import BaseScraper

_REGISTRY: dict[str, type] = {}


def register(site_name: str):
    def _decorator(cls: type[BaseScraper]) -> type[BaseScraper]:
        _REGISTRY[site_name] = cls
        return cls

    return _decorator


def get_scraper(site_name: str) -> BaseScraper:
    if site_name not in _REGISTRY:
        raise ValueError(f"Unknown scraper site '{site_name}'. Registered: {sorted(_REGISTRY)}")
    return _REGISTRY[site_name]()


def registered_sites() -> list[str]:
    return sorted(_REGISTRY)
