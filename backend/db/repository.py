"""Async repository layer for Job, OrganicJob, and UserCorrection models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import JobModel, OrganicJobModel, UserCorrectionModel


# ---------------------------------------------------------------------------
# JobModel CRUD
# ---------------------------------------------------------------------------


async def create_job(
    session: AsyncSession, job_id: str, **kwargs: Any,
) -> JobModel:
    """Create a new job and flush (but do not commit)."""
    job = JobModel(job_id=job_id, **kwargs)
    session.add(job)
    await session.flush()
    return job


async def get_job(
    session: AsyncSession, job_id: str,
) -> JobModel | None:
    """Return a job by ID, or None."""
    return await session.get(JobModel, job_id)


async def update_job(
    session: AsyncSession, job_id: str, **kwargs: Any,
) -> JobModel:
    """Update a job's fields. Raises KeyError if not found."""
    job = await session.get(JobModel, job_id)
    if job is None:
        raise KeyError(f"Job {job_id} not found")
    for key, value in kwargs.items():
        setattr(job, key, value)
    await session.flush()
    return job


async def list_jobs(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    input_type: str | None = None,
) -> tuple[list[JobModel], int]:
    """Return a paginated list of jobs and total count.

    Filters by status and/or input_type when provided.
    """
    stmt = select(JobModel)
    count_stmt = select(func.count()).select_from(JobModel)

    if status is not None:
        stmt = stmt.where(JobModel.status == status)
        count_stmt = count_stmt.where(JobModel.status == status)
    if input_type is not None:
        stmt = stmt.where(JobModel.input_type == input_type)
        count_stmt = count_stmt.where(JobModel.input_type == input_type)

    stmt = stmt.order_by(JobModel.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    jobs = list(result.scalars().all())

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return jobs, total


# ---------------------------------------------------------------------------
# OrganicJobModel CRUD
# ---------------------------------------------------------------------------


async def create_organic_job(
    session: AsyncSession, job_id: str, **kwargs: Any,
) -> OrganicJobModel:
    """Create a new organic job and flush."""
    job = OrganicJobModel(job_id=job_id, **kwargs)
    session.add(job)
    await session.flush()
    return job


async def get_organic_job(
    session: AsyncSession, job_id: str,
) -> OrganicJobModel | None:
    """Return an organic job by ID, or None."""
    return await session.get(OrganicJobModel, job_id)


async def update_organic_job(
    session: AsyncSession, job_id: str, **kwargs: Any,
) -> OrganicJobModel:
    """Update an organic job's fields. Raises KeyError if not found."""
    job = await session.get(OrganicJobModel, job_id)
    if job is None:
        raise KeyError(f"OrganicJob {job_id} not found")
    for key, value in kwargs.items():
        setattr(job, key, value)
    await session.flush()
    return job


async def list_organic_jobs(
    session: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> tuple[list[OrganicJobModel], int]:
    """Return a paginated list of organic jobs and total count."""
    stmt = select(OrganicJobModel)
    count_stmt = select(func.count()).select_from(OrganicJobModel)

    if status is not None:
        stmt = stmt.where(OrganicJobModel.status == status)
        count_stmt = count_stmt.where(OrganicJobModel.status == status)

    stmt = stmt.order_by(OrganicJobModel.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    jobs = list(result.scalars().all())

    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    return jobs, total


# ---------------------------------------------------------------------------
# UserCorrectionModel CRUD
# ---------------------------------------------------------------------------


async def create_correction(
    session: AsyncSession, **kwargs: Any,
) -> UserCorrectionModel:
    """Create a new user correction and flush."""
    correction = UserCorrectionModel(**kwargs)
    session.add(correction)
    await session.flush()
    return correction


async def list_corrections_by_job(
    session: AsyncSession, job_id: str,
) -> list[UserCorrectionModel]:
    """Return all corrections for a given job."""
    stmt = (
        select(UserCorrectionModel)
        .where(UserCorrectionModel.job_id == job_id)
        .order_by(UserCorrectionModel.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
