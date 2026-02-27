"""History API endpoints — list, detail, regenerate, delete jobs."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_session
from backend.db.repository import (
    create_job,
    get_job,
    list_corrections_by_job,
    list_jobs,
    update_job,
)
from backend.models.job import JobStatus

router = APIRouter(prefix="/jobs", tags=["history"])


# ---------------------------------------------------------------------------
# List jobs (paginated + filtered)
# ---------------------------------------------------------------------------


@router.get("")
async def list_jobs_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    input_type: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return paginated list of jobs with optional status/input_type filter."""
    jobs, total = await list_jobs(
        session, page=page, page_size=page_size,
        status=status, input_type=input_type,
    )
    return {
        "items": [_job_summary(j) for j in jobs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Job detail (includes corrections)
# ---------------------------------------------------------------------------


@router.get("/{job_id}")
async def get_job_detail(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return full job detail including user corrections."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    corrections = await list_corrections_by_job(session, job_id)

    detail = _job_summary(job)
    detail["intent"] = job.intent
    detail["precise_spec"] = job.precise_spec
    detail["drawing_spec"] = job.drawing_spec
    detail["drawing_spec_confirmed"] = job.drawing_spec_confirmed
    detail["image_path"] = job.image_path
    detail["recommendations"] = job.recommendations or []
    detail["corrections"] = [
        {
            "id": c.id,
            "field_path": c.field_path,
            "original_value": c.original_value,
            "corrected_value": c.corrected_value,
            "timestamp": c.timestamp.isoformat() if c.timestamp else None,
        }
        for c in corrections
    ]
    return detail


# ---------------------------------------------------------------------------
# Regenerate (clone job with new ID)
# ---------------------------------------------------------------------------


@router.post("/{job_id}/regenerate")
async def regenerate_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new job cloned from an existing one."""
    original = await get_job(session, job_id)
    if original is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    new_id = str(uuid.uuid4())
    new_job = await create_job(
        session,
        job_id=new_id,
        status=JobStatus.CREATED.value,
        input_type=original.input_type or "text",
        input_text=original.input_text or "",
        recommendations=[],
    )
    await session.commit()

    return {
        "job_id": new_job.job_id,
        "cloned_from": job_id,
        "status": new_job.status,
    }


# ---------------------------------------------------------------------------
# Delete job
# ---------------------------------------------------------------------------


@router.delete("/{job_id}")
async def delete_job_endpoint(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Soft-delete a job by marking it as failed with deletion note."""
    job = await get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    await update_job(session, job_id, status=JobStatus.FAILED.value, error="deleted")
    await session.commit()

    return {"job_id": job_id, "deleted": "true"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_summary(job: Any) -> dict[str, Any]:
    """Build a summary dict from a JobModel ORM instance."""
    created_at = ""
    if job.created_at is not None:
        from datetime import datetime
        created_at = (
            job.created_at.isoformat()
            if isinstance(job.created_at, datetime)
            else str(job.created_at)
        )

    return {
        "job_id": job.job_id,
        "status": job.status,
        "input_type": job.input_type or "text",
        "input_text": job.input_text or "",
        "result": job.result,
        "printability_result": job.printability_result,
        "error": job.error,
        "created_at": created_at,
    }
