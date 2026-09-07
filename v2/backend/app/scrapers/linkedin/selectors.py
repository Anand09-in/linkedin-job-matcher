"""
CSS selectors for LinkedIn's authenticated jobs-search UI.

Ported from the working selector strings in v1's `linkedin-jobs-scraper`
dependency (its AuthenticatedStrategy.Selectors) rather than guessed from
scratch — see system-design.md decision log #3 for why v2 owns these
directly instead of depending on that library: its selector bugs (empty
date_posted for every job, traced to this exact DATE selector) were
unfixable from our side.

Isolated in their own module — not inlined in adapter.py — so a future
LinkedIn markup change is a one-file diff instead of a hunt through the
adapter's control flow.
"""

CONTAINER = ".scaffold-layout__list"
JOB_CARD = "div.job-card-container"
JOB_LINK = "a.job-card-container__link"
TITLE = ".artdeco-entity-lockup__title"
COMPANY = ".artdeco-entity-lockup__subtitle"
PLACE = ".artdeco-entity-lockup__caption"
DATE = "time"  # read the `datetime` attribute — this is the field v1 lost
DESCRIPTION = ".jobs-description"
INSIGHTS = ".job-details-jobs-unified-top-card__container--two-pane li"
APPLY_BUTTON = 'button.jobs-apply-button[role="link"]'

# No dedicated class for the "Promoted" badge on a card — v1's library
# scanned every <li> in the card for this exact text, and that's what we do
# too (see adapter.py's _is_promoted). Sponsored/promoted listings carry no
# posted-date at all, which is why this matters: it turns a missing
# date_posted into an explained case instead of a silent extraction gap.
CARD_LIST_ITEMS = "li"
PROMOTED_LABEL = "Promoted"
