"""
The one place allowed to name every adapter — FR-1.3 says adding a new site
"requires only a new adapter module + registry entry"; this module IS that
registry entry. Kept separate from registry.py (which must stay pure
mechanism with zero site-specific mentions) so the "add one line here" step
FR-1.3 explicitly permits has an obvious, single, minimal home instead of
sprawling into files that are supposed to be site-agnostic.

Call once at process startup (worker_app.py, and any test that needs the
registry populated — see tests/conftest.py).
"""
from __future__ import annotations


def bootstrap() -> None:
    import app.scrapers.linkedin.adapter  # noqa: F401
    import app.scrapers.testsite.adapter  # noqa: F401
