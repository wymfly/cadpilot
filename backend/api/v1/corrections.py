"""Correction analytics API — GET /api/v1/corrections/stats.

Provides aggregated statistics on user corrections to identify
common AI prediction errors and guide model improvement.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.db.database import async_session
from backend.db.models import JobModel, UserCorrectionModel

router = APIRouter(prefix="/corrections", tags=["corrections"])


class FieldStat(BaseModel):
    """A single field correction statistic."""

    field_path: str
    count: int
    percent: float


class CorrectionStatsResponse(BaseModel):
    """Response for correction statistics endpoint."""

    top_fields: list[FieldStat] = Field(default_factory=list)


@router.get("/stats", response_model=CorrectionStatsResponse)
async def get_correction_stats(
    part_type: str | None = Query(None, description="Filter by part_type in job intent"),
) -> CorrectionStatsResponse:
    """Return top corrected fields with counts and percentages.

    Optionally filter by part_type (matched against intent->part_type in jobs table).
    Returns at most 20 entries, ordered by count descending.
    """
    async with async_session() as session:
        # Base query: count corrections grouped by field_path
        # Exclude noop corrections (original == corrected) and empty values
        base_filter = [
            UserCorrectionModel.field_path != "",
            UserCorrectionModel.corrected_value != "",
            UserCorrectionModel.original_value != UserCorrectionModel.corrected_value,
        ]

        if part_type:
            # Join with jobs table to filter by intent->part_type
            stmt = (
                select(
                    UserCorrectionModel.field_path,
                    func.count().label("cnt"),
                )
                .join(
                    JobModel,
                    UserCorrectionModel.job_id == JobModel.job_id,
                )
                .where(*base_filter)
                .where(
                    func.json_extract(JobModel.intent, "$.part_type") == part_type,
                )
                .group_by(UserCorrectionModel.field_path)
                .order_by(func.count().desc())
                .limit(20)
            )
        else:
            stmt = (
                select(
                    UserCorrectionModel.field_path,
                    func.count().label("cnt"),
                )
                .where(*base_filter)
                .group_by(UserCorrectionModel.field_path)
                .order_by(func.count().desc())
                .limit(20)
            )

        result = await session.execute(stmt)
        rows = result.all()

        if not rows:
            return CorrectionStatsResponse(top_fields=[])

        # Total count across ALL matching corrections (not just top-20)
        if part_type:
            total_stmt = (
                select(func.count())
                .select_from(UserCorrectionModel)
                .join(JobModel, UserCorrectionModel.job_id == JobModel.job_id)
                .where(*base_filter)
                .where(func.json_extract(JobModel.intent, "$.part_type") == part_type)
            )
        else:
            total_stmt = (
                select(func.count())
                .select_from(UserCorrectionModel)
                .where(*base_filter)
            )
        total_result = await session.execute(total_stmt)
        total = total_result.scalar() or 0

        top_fields = [
            FieldStat(
                field_path=r.field_path,
                count=r.cnt,
                percent=round(r.cnt / total * 100, 1) if total > 0 else 0.0,
            )
            for r in rows
        ]

    return CorrectionStatsResponse(top_fields=top_fields)
