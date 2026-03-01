"""Tests for Job model lifecycle and PipelineConfig parsing.

Originally contained tests for legacy /api/generate, /api/generate/drawing,
and /api/generate/{job_id}/confirm SSE routes.  Those routes were removed in
Phase 5b (V1 migration) and the corresponding route tests were deleted.

V1 equivalents live in:
- test_api_v1.py (POST /api/v1/jobs, SSE, confirm, upload)
- test_history_api.py (GET /api/v1/jobs, job detail, regenerate, delete)
- test_preview_api.py (POST /api/v1/preview/parametric)

Remaining tests here are route-independent:
- TestJobModel — in-memory Job CRUD
- TestParsePipelineConfig — PipelineConfig parsing
"""

from __future__ import annotations

import pytest

from backend.models.job import (
    Job,
    JobStatus,
    clear_jobs,
    create_job,
    delete_job,
    get_job,
    list_jobs,
    update_job,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
async def _init_and_clean_jobs():
    """Init DB tables and clear job store before each test."""
    import backend.db.models  # noqa: F401 — register ORM models with Base
    from backend.db.database import init_db

    await init_db()
    await clear_jobs()
    yield
    await clear_jobs()


# ===================================================================
# Job model unit tests
# ===================================================================


class TestJobModel:
    async def test_create_job(self) -> None:
        job = await create_job("j1", input_type="text", input_text="做一个法兰")
        assert job.job_id == "j1"
        assert job.status == JobStatus.CREATED
        assert job.input_type == "text"
        assert job.input_text == "做一个法兰"

    async def test_get_job(self) -> None:
        await create_job("j2")
        job = await get_job("j2")
        assert job is not None
        assert job.job_id == "j2"

    async def test_get_nonexistent(self) -> None:
        assert await get_job("nonexistent") is None

    async def test_update_job(self) -> None:
        await create_job("j3")
        await update_job("j3", status=JobStatus.GENERATING)
        job = await get_job("j3")
        assert job is not None
        assert job.status == JobStatus.GENERATING

    async def test_update_nonexistent_raises(self) -> None:
        with pytest.raises(KeyError):
            await update_job("nonexistent", status=JobStatus.COMPLETED)

    async def test_delete_job(self) -> None:
        await create_job("j4")
        await delete_job("j4")
        assert await get_job("j4") is None

    async def test_list_jobs(self) -> None:
        await create_job("a")
        await create_job("b")
        jobs = await list_jobs()
        assert len(jobs) == 2

    async def test_clear_jobs(self) -> None:
        await create_job("x")
        await create_job("y")
        await clear_jobs()
        assert await list_jobs() == []

    async def test_job_status_enum(self) -> None:
        assert JobStatus.CREATED.value == "created"
        assert JobStatus.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
        assert JobStatus.COMPLETED.value == "completed"

    async def test_job_serialization(self) -> None:
        job = await create_job("s1", input_type="text", input_text="test")
        data = job.model_dump()
        assert data["job_id"] == "s1"
        assert data["status"] == "created"
        restored = Job.model_validate(data)
        assert restored.job_id == "s1"

    async def test_job_status_transitions(self) -> None:
        await create_job("t1")
        for status in [
            JobStatus.INTENT_PARSED,
            JobStatus.AWAITING_CONFIRMATION,
            JobStatus.AWAITING_DRAWING_CONFIRMATION,
            JobStatus.GENERATING,
            JobStatus.REFINING,
            JobStatus.COMPLETED,
        ]:
            await update_job("t1", status=status)
            assert (await get_job("t1")).status == status

    async def test_awaiting_drawing_confirmation_status(self) -> None:
        assert (
            JobStatus.AWAITING_DRAWING_CONFIRMATION.value
            == "awaiting_drawing_confirmation"
        )

    async def test_drawing_spec_fields(self) -> None:
        job = await create_job("d1", input_type="drawing")
        assert job.drawing_spec is None
        assert job.drawing_spec_confirmed is None
        assert job.image_path is None

        spec = {"part_type": "ROTATIONAL", "overall_dimensions": {"d": 50}}
        await update_job(
            "d1",
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=spec,
            image_path="/uploads/drawing.png",
        )
        job = await get_job("d1")
        assert job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
        assert job.drawing_spec == spec
        assert job.image_path == "/uploads/drawing.png"

        confirmed = {**spec, "overall_dimensions": {"d": 52}}
        await update_job("d1", drawing_spec_confirmed=confirmed)
        job = await get_job("d1")
        assert job.drawing_spec_confirmed == confirmed

    async def test_drawing_job_serialization(self) -> None:
        await create_job("d2", input_type="drawing")
        spec = {"part_type": "PLATE", "overall_dimensions": {"w": 100}}
        await update_job(
            "d2",
            drawing_spec=spec,
            image_path="/tmp/img.jpg",
        )
        data = (await get_job("d2")).model_dump()
        assert data["drawing_spec"] == spec
        assert data["image_path"] == "/tmp/img.jpg"
        restored = Job.model_validate(data)
        assert restored.drawing_spec == spec


# ===================================================================
# _parse_pipeline_config input variants
# ===================================================================


class TestParsePipelineConfig:
    """Tests for _parse_pipeline_config edge cases."""

    def test_valid_preset(self) -> None:
        from backend.models.pipeline_config import _parse_pipeline_config

        config = _parse_pipeline_config('{"preset": "fast"}')
        assert config is not None

    def test_invalid_json(self) -> None:
        from backend.models.pipeline_config import _parse_pipeline_config

        config = _parse_pipeline_config("not json at all")
        # Should fall back to balanced preset
        assert config is not None

    def test_empty_string(self) -> None:
        from backend.models.pipeline_config import _parse_pipeline_config

        config = _parse_pipeline_config("")
        assert config is not None

    def test_non_dict_json(self) -> None:
        from backend.models.pipeline_config import _parse_pipeline_config

        config = _parse_pipeline_config("[1, 2, 3]")
        # Non-dict should fall back to balanced
        assert config is not None

    def test_empty_dict(self) -> None:
        from backend.models.pipeline_config import _parse_pipeline_config

        config = _parse_pipeline_config("{}")
        assert config is not None

    def test_unknown_preset(self) -> None:
        from pydantic import ValidationError

        from backend.models.pipeline_config import _parse_pipeline_config

        # Unknown preset falls through to PipelineConfig(**raw) which raises
        # ValidationError because preset is Literal["fast","balanced","precise","custom"]
        with pytest.raises(ValidationError):
            _parse_pipeline_config('{"preset": "nonexistent"}')
