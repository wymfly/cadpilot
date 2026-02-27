"""Job session model for the generate workflow (Phase 4 Task 4.6).

A Job tracks the lifecycle of a single generate request:
CREATED → INTENT_PARSED → AWAITING_CONFIRMATION → GENERATING → REFINING → COMPLETED
                                                                          ↗
                                              VALIDATION_FAILED → (retry or abort)

Drawing path adds an intermediate step:
CREATED → AWAITING_DRAWING_CONFIRMATION → GENERATING → REFINING → COMPLETED
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.models.intent import IntentSpec, PreciseSpec


class JobStatus(str, Enum):
    """Lifecycle states for a generate job."""

    CREATED = "created"
    INTENT_PARSED = "intent_parsed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_DRAWING_CONFIRMATION = "awaiting_drawing_confirmation"
    GENERATING = "generating"
    REFINING = "refining"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"


class Job(BaseModel):
    """In-memory job record."""

    job_id: str
    status: JobStatus = JobStatus.CREATED
    input_type: str = "text"  # "text" | "drawing"
    input_text: str = ""
    intent: Optional[IntentSpec] = None
    precise_spec: Optional[PreciseSpec] = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    drawing_spec: Optional[dict[str, Any]] = None
    drawing_spec_confirmed: Optional[dict[str, Any]] = None
    image_path: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_jobs: dict[str, Job] = {}


def create_job(job_id: str, input_type: str = "text", input_text: str = "") -> Job:
    """Create and store a new job."""
    job = Job(job_id=job_id, input_type=input_type, input_text=input_text)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[Job]:
    """Retrieve a job by ID, or None."""
    return _jobs.get(job_id)


def update_job(job_id: str, **kwargs: Any) -> Job:
    """Update fields on an existing job. Raises KeyError if not found."""
    job = _jobs[job_id]
    for k, v in kwargs.items():
        setattr(job, k, v)
    return job


def delete_job(job_id: str) -> None:
    """Remove a job from the store."""
    _jobs.pop(job_id, None)


def list_jobs() -> list[Job]:
    """Return all jobs."""
    return list(_jobs.values())


def clear_jobs() -> None:
    """Clear all jobs (for testing)."""
    _jobs.clear()
