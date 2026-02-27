"""Organic job session model for the organic generation pipeline.

Parallel to backend/models/job.py but for organic generation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.models.organic import OrganicJobResult


class OrganicJobStatus(str, Enum):
    """Lifecycle states for an organic generation job."""

    CREATED = "created"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"


class OrganicJob(BaseModel):
    """In-memory organic job record."""

    job_id: str
    status: OrganicJobStatus = OrganicJobStatus.CREATED
    prompt: str = ""
    provider: str = "auto"
    quality_mode: str = "standard"
    progress: float = 0.0
    message: str = ""
    result: Optional[OrganicJobResult] = None
    error: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_organic_jobs: dict[str, OrganicJob] = {}


def create_organic_job(
    job_id: str,
    prompt: str = "",
    provider: str = "auto",
    quality_mode: str = "standard",
) -> OrganicJob:
    """Create and store a new organic job."""
    job = OrganicJob(
        job_id=job_id,
        prompt=prompt,
        provider=provider,
        quality_mode=quality_mode,
    )
    _organic_jobs[job_id] = job
    return job


def get_organic_job(job_id: str) -> Optional[OrganicJob]:
    """Retrieve an organic job by ID, or None."""
    return _organic_jobs.get(job_id)


def update_organic_job(job_id: str, **kwargs: Any) -> OrganicJob:
    """Update fields on an existing organic job. Raises KeyError if not found."""
    job = _organic_jobs[job_id]
    for k, v in kwargs.items():
        setattr(job, k, v)
    return job


def delete_organic_job(job_id: str) -> None:
    """Remove an organic job from the store."""
    _organic_jobs.pop(job_id, None)


def list_organic_jobs() -> list[OrganicJob]:
    """Return all organic jobs."""
    return list(_organic_jobs.values())


def clear_organic_jobs() -> None:
    """Clear all organic jobs (for testing)."""
    _organic_jobs.clear()
