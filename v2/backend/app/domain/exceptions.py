"""Domain-level exceptions — raised by the repository, translated to HTTP status
codes by the API layer in Phase 7 (e.g. ResumeInUseError -> 409)."""
from __future__ import annotations


class ResumeInUseError(Exception):
    """Raised when deleting a Resume still referenced by an enabled Pipeline (FR-1A.7)."""

    def __init__(self, resume_id, pipeline_names: list[str]):
        self.resume_id = resume_id
        self.pipeline_names = pipeline_names
        super().__init__(
            f"Resume {resume_id} is still bound to enabled pipeline(s): "
            f"{', '.join(pipeline_names)}. Disable or reassign them first."
        )


class FeatureRequiresResumeError(Exception):
    """Raised by feature_service.py (FR-6, Phase 6) when an on-demand feature
    that needs a resume (all of them except company_research) is requested
    for a job whose pipeline had no resume bound (FR-2.6 extract-only mode) —
    translated to HTTP 422 by main.py."""

    def __init__(self, feature: str, job_id):
        self.feature = feature
        self.job_id = job_id
        super().__init__(
            f"Feature '{feature}' requires a resume, but job {job_id} came from a pipeline with no "
            f"resume bound (extract-only mode). Run this job through a resume-bound pipeline instead."
        )


class UnknownFeatureError(Exception):
    """Raised by feature_service.py when `feature` isn't one of the
    registered Phase 6 features — translated to HTTP 404 by main.py."""

    def __init__(self, feature: str, known: list[str]):
        self.feature = feature
        self.known = known
        super().__init__(f"Unknown feature '{feature}'. Known features: {', '.join(known)}.")
