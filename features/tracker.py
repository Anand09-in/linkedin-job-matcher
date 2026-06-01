"""
Feature module: tracker
Kanban-style application tracker — board building and analytics.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from loguru import logger
from pydantic import BaseModel


VALID_STATUSES = ["new", "saved", "applied", "interview", "offer", "rejected"]

KANBAN_COLUMNS = {
    "new":       "New",
    "saved":     "Saved",
    "applied":   "Applied",
    "interview": "Interview",
    "offer":     "Offer",
    "rejected":  "Rejected",
}

STATUS_TRANSITIONS: dict[str, list[str]] = {
    "new":       ["saved", "applied", "rejected"],
    "saved":     ["applied", "rejected"],
    "applied":   ["interview", "rejected"],
    "interview": ["offer", "rejected"],
    "offer":     [],
    "rejected":  ["saved"],
}


class KanbanColumn(BaseModel):
    status: str
    label: str
    count: int
    jobs: list[dict]


class TrackerBoard(BaseModel):
    columns: list[KanbanColumn]
    total_tracked: int
    active_pipeline: int         # saved + applied + interview + offer
    conversion_rate: Optional[float]  # applied → interview rate


class ApplicationStats(BaseModel):
    total_saved: int
    total_applied: int
    total_interviews: int
    total_offers: int
    total_rejected: int
    apply_to_interview_rate: float
    interview_to_offer_rate: float


def build_kanban_board(jobs: list[dict]) -> TrackerBoard:
    """Organise jobs into Kanban columns."""
    groups: dict[str, list[dict]] = {s: [] for s in VALID_STATUSES}
    for job in jobs:
        status = job.get("status", "new")
        groups.setdefault(status, groups["new"]).append(job) if status in groups else groups["new"].append(job)

    columns = [
        KanbanColumn(
            status=status,
            label=KANBAN_COLUMNS[status],
            count=len(groups[status]),
            jobs=groups[status],
        )
        for status in VALID_STATUSES
    ]

    active = sum(len(groups[s]) for s in ["saved", "applied", "interview", "offer"])
    applied_total = sum(len(groups[s]) for s in ["applied", "interview", "offer"])
    interviews = sum(len(groups[s]) for s in ["interview", "offer"])
    conversion = round(interviews / applied_total, 3) if applied_total > 0 else None

    return TrackerBoard(
        columns=columns,
        total_tracked=len(jobs),
        active_pipeline=active,
        conversion_rate=conversion,
    )


def get_application_stats(jobs: list[dict]) -> ApplicationStats:
    """Compute funnel statistics across all tracked applications."""
    counts = Counter(job.get("status", "new") for job in jobs)

    applied = counts.get("applied", 0) + counts.get("interview", 0) + counts.get("offer", 0)
    interviews = counts.get("interview", 0) + counts.get("offer", 0)
    offers = counts.get("offer", 0)

    return ApplicationStats(
        total_saved=counts.get("saved", 0),
        total_applied=applied,
        total_interviews=counts.get("interview", 0),
        total_offers=offers,
        total_rejected=counts.get("rejected", 0),
        apply_to_interview_rate=round(interviews / applied, 3) if applied > 0 else 0.0,
        interview_to_offer_rate=round(offers / interviews, 3) if interviews > 0 else 0.0,
    )


def can_transition(current_status: str, new_status: str) -> bool:
    """Return True if the status transition is valid."""
    return new_status in STATUS_TRANSITIONS.get(current_status, [])
