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
