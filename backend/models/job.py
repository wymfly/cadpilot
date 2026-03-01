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
    """Job record (API-layer data object)."""

    job_id: str
    status: JobStatus = JobStatus.CREATED
    input_type: str = "text"  # "text" | "drawing"
    input_text: str = ""
    intent: dict[str, Any] | None = None
    precise_spec: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    drawing_spec: Optional[dict[str, Any]] = None
    drawing_spec_confirmed: Optional[dict[str, Any]] = None
    image_path: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    printability: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# ORM ↔ Pydantic conversion
# ---------------------------------------------------------------------------


def _orm_to_job(orm: Any) -> Job:
    """Convert a JobModel ORM instance to a Pydantic Job."""
    created_at = ""
    if orm.created_at is not None:
        created_at = (
            orm.created_at.isoformat()
            if isinstance(orm.created_at, datetime)
            else str(orm.created_at)
        )
    return Job(
        job_id=orm.job_id,
        status=JobStatus(orm.status),
        input_type=orm.input_type or "text",
        input_text=orm.input_text or "",
        intent=orm.intent,
        precise_spec=orm.precise_spec,
        recommendations=orm.recommendations or [],
        drawing_spec=orm.drawing_spec,
        drawing_spec_confirmed=orm.drawing_spec_confirmed,
        image_path=orm.image_path,
        result=orm.result,
        printability=orm.printability_result,
        error=orm.error,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Async job store (delegates to SQLite repository)
# ---------------------------------------------------------------------------


async def create_job(
    job_id: str, input_type: str = "text", input_text: str = "",
) -> Job:
    """Create and persist a new job."""
    from backend.db.database import async_session
    from backend.db.repository import create_job as repo_create

    async with async_session() as session:
        orm_job = await repo_create(
            session,
            job_id=job_id,
            status=JobStatus.CREATED.value,
            input_type=input_type,
            input_text=input_text,
            recommendations=[],
        )
        await session.commit()
        return _orm_to_job(orm_job)


async def get_job(job_id: str) -> Optional[Job]:
    """Retrieve a job by ID, or None."""
    from backend.db.database import async_session
    from backend.db.repository import get_job as repo_get

    async with async_session() as session:
        orm_job = await repo_get(session, job_id)
        if orm_job is None:
            return None
        return _orm_to_job(orm_job)


async def update_job(job_id: str, **kwargs: Any) -> Job:
    """Update fields on an existing job. Raises KeyError if not found."""
    from backend.db.database import async_session
    from backend.db.repository import update_job as repo_update

    async with async_session() as session:
        orm_job = await repo_update(session, job_id, **kwargs)
        await session.commit()
        return _orm_to_job(orm_job)


async def delete_job(job_id: str) -> None:
    """Remove a job from the store."""
    from backend.db.database import async_session
    from backend.db.models import JobModel

    async with async_session() as session:
        orm_job = await session.get(JobModel, job_id)
        if orm_job is not None:
            await session.delete(orm_job)
            await session.commit()


async def list_jobs() -> list[Job]:
    """Return all jobs."""
    from backend.db.database import async_session
    from backend.db.repository import list_jobs as repo_list

    async with async_session() as session:
        orm_jobs, _ = await repo_list(session, page=1, page_size=10000)
        return [_orm_to_job(j) for j in orm_jobs]


async def clear_jobs() -> None:
    """Clear all jobs (for testing)."""
    from sqlalchemy import delete as sa_delete

    from backend.db.database import async_session
    from backend.db.models import JobModel

    async with async_session() as session:
        await session.execute(sa_delete(JobModel))
        await session.commit()
