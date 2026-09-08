"""
Shared persistent-profile browser launcher for the LinkedIn adapter
(adapter.py) and its cookie-validity checker (cookie_check.py).

Real, live problem this fixes: both used to call `browser.launch()` +
`browser.new_context()` — a fresh, isolated browser profile every single
call. To LinkedIn, that looks exactly like the same session cookie logging
in from a different device each time, which its account-security systems
treat as suspicious multi-device access and respond to by force-invalidating
the session — independent of the cookie's real ~30-day expiry. A user
reported LinkedIn logging them out far more often after this project started
hitting it this way than it did with v1's Selenium-based scraper, which
didn't churn a fresh profile per run.

`launch_persistent_context` with a fixed, volume-backed `user_data_dir`
(docker-compose.yml's `jm2_linkedin_profile`) keeps the same profile —
cookies, local storage, cache, fingerprint-relevant state — across every
run AND across container restarts, so LinkedIn sees one consistent device
instead of a new one each time.

Known limitation, accepted rather than engineered around: Chromium locks a
profile directory to one running process, so two LinkedIn scrapes (or a
scrape and a cookie check) can't run concurrently — arq would need to
serialize them (e.g. a semaphore keyed by site) for that to be safe. Not
implemented: a personal tool's realistic usage is one pipeline triggered at
a time, and the failure mode of a genuine overlap is a clear launch error,
not silent data corruption.
"""
from __future__ import annotations

from playwright.async_api import BrowserContext

PROFILE_DIR = "/data/linkedin-profile"


async def launch_linkedin_context(pw, cookie: str) -> BrowserContext:
    context = await pw.chromium.launch_persistent_context(PROFILE_DIR, headless=True)
    await context.add_cookies([{
        "name": "li_at",
        "value": cookie,
        "domain": ".www.linkedin.com",
        "path": "/",
    }])
    return context
