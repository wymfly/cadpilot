"""Async repository layer for Job, OrganicJob, and UserCorrection models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


async def soft_delete_job(
    session: AsyncSession, job_id: str,
) -> JobModel:
    """Soft-delete a job by setting deleted_at. Raises KeyError if not found."""
    job = await session.get(JobModel, job_id)
    if job is None:
        raise KeyError(f"Job {job_id} not found")
    job.deleted_at = datetime.now(timezone.utc)
    job.status = "failed"
    job.error = "deleted by user"
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
    Excludes soft-deleted jobs.
    """
    stmt = select(JobModel).where(JobModel.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(JobModel).where(
        JobModel.deleted_at.is_(None),
    )

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


# ---------------------------------------------------------------------------
# SQLiteJobRepository — 封装类实现 JobRepository Protocol
# ---------------------------------------------------------------------------


class SQLiteJobRepository:
    """SQLite 实现的 JobRepository，封装独立的 CRUD 函数。

    每个方法自动管理 session + commit，调用方无需手动管理事务。
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, job_id: str, **kwargs: Any) -> JobModel:
        async with self._session_factory() as session:
            job = await create_job(session, job_id, **kwargs)
            await session.commit()
            return job

    async def get(self, job_id: str) -> JobModel | None:
        async with self._session_factory() as session:
            return await get_job(session, job_id)

    async def update(self, job_id: str, **kwargs: Any) -> JobModel:
        async with self._session_factory() as session:
            job = await update_job(session, job_id, **kwargs)
            await session.commit()
            return job

    async def soft_delete(self, job_id: str) -> None:
        async with self._session_factory() as session:
            await soft_delete_job(session, job_id)
            await session.commit()

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        input_type: str | None = None,
    ) -> tuple[list[JobModel], int]:
        async with self._session_factory() as session:
            return await list_jobs(
                session, page=page, page_size=page_size,
                status=status, input_type=input_type,
            )
