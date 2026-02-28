"""SQLAlchemy ORM models for Job, OrganicJob, and UserCorrection."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.database import Base


class JobModel(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Valid: created, intent_parsed, awaiting_confirmation,
    # awaiting_drawing_confirmation, generating, refining, completed, failed
    status: Mapped[str] = mapped_column(String(32), default="created")
    input_type: Mapped[str] = mapped_column(String(16), default="text")  # text | drawing
    input_text: Mapped[str] = mapped_column(Text, default="")
    intent: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    precise_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    drawing_spec: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    drawing_spec_confirmed: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    printability_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class OrganicJobModel(Base):
    __tablename__ = "organic_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Valid: created, analyzing, generating, post_processing, completed, failed
    status: Mapped[str] = mapped_column(String(32), default="created")
    prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="auto")  # auto | tripo3d | hunyuan3d
    quality_mode: Mapped[str] = mapped_column(String(16), default="standard")  # draft | standard | high
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    printability_result: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class UserCorrectionModel(Base):
    __tablename__ = "user_corrections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # No ForeignKey: corrections may reference jobs in the in-memory store
    # (drawing flow) that are not persisted to the jobs table.
    job_id: Mapped[str] = mapped_column(String(64), index=True)
    field_path: Mapped[str] = mapped_column(String(256))
    original_value: Mapped[str] = mapped_column(Text)
    corrected_value: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
