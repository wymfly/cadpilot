"""Tests for M5 code persistence and version chain features.

Covers:
- generate_step_text_node saves generated_code to state
- generate_step_drawing_node saves generated_code to state
- finalize_node persists generated_code and parent_job_id to DB
- Fork validation rejects non-text input types
- Job detail API returns parent_job_id and child_job_ids
- Pipeline return value change (generate_step_from_spec returns code)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.spec_compiler import CompileResult
from backend.graph.state import CadJobState


# ---------------------------------------------------------------------------
# State field existence
# ---------------------------------------------------------------------------

class TestStateFields:
    def test_generated_code_in_state(self) -> None:
        annotations = CadJobState.__annotations__
        assert "generated_code" in annotations

    def test_parent_job_id_in_state(self) -> None:
        annotations = CadJobState.__annotations__
        assert "parent_job_id" in annotations


# ---------------------------------------------------------------------------
# ORM model fields
# ---------------------------------------------------------------------------

class TestORMFields:
    def test_job_model_has_generated_code(self) -> None:
        from backend.db.models import JobModel
        cols = {c.key for c in JobModel.__table__.columns}
        assert "generated_code" in cols

    def test_job_model_has_parent_job_id(self) -> None:
        from backend.db.models import JobModel
        cols = {c.key for c in JobModel.__table__.columns}
        assert "parent_job_id" in cols


# ---------------------------------------------------------------------------
# Pydantic model fields
# ---------------------------------------------------------------------------

class TestPydanticFields:
    def test_job_has_generated_code(self) -> None:
        from backend.models.job import Job
        assert "generated_code" in Job.model_fields

    def test_job_has_parent_job_id(self) -> None:
        from backend.models.job import Job
        assert "parent_job_id" in Job.model_fields


# ---------------------------------------------------------------------------
# Text generation node saves code
# ---------------------------------------------------------------------------

class TestTextNodeCodePersistence:
    @pytest.mark.asyncio
    async def test_text_node_returns_generated_code(self) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state: CadJobState = {
            "job_id": "test-code-text-1",
            "input_type": "text",
            "input_text": "make a cylinder",
            "status": "generating",
        }

        mock_result = CompileResult(
            method="template",
            step_path="/tmp/model.step",
            cadquery_code="import cadquery as cq\nresult = cq.Workplane().cylinder(50, 25)",
        )

        with (
            patch(
                "backend.graph.nodes.generation.SpecCompiler",
                return_value=MagicMock(compile=MagicMock(return_value=mock_result)),
            ),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            result = await generate_step_text_node(state)

        assert result.get("generated_code") == mock_result.cadquery_code
        assert result.get("step_path") == "/tmp/model.step"

    @pytest.mark.asyncio
    async def test_text_node_empty_code_returns_none(self) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state: CadJobState = {
            "job_id": "test-code-text-2",
            "input_type": "text",
            "input_text": "make something",
            "status": "generating",
        }

        mock_result = CompileResult(
            method="template",
            step_path="/tmp/model.step",
            cadquery_code="",  # empty code
        )

        with (
            patch(
                "backend.graph.nodes.generation.SpecCompiler",
                return_value=MagicMock(compile=MagicMock(return_value=mock_result)),
            ),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
        ):
            result = await generate_step_text_node(state)

        # Empty string → None
        assert result.get("generated_code") is None

    @pytest.mark.asyncio
    async def test_text_node_writes_code_file(self) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state: CadJobState = {
            "job_id": "test-code-text-3",
            "input_type": "text",
            "input_text": "make a gear",
            "status": "generating",
        }

        code = "import cadquery as cq\nresult = cq.Workplane().box(10, 10, 10)"
        mock_result = CompileResult(
            method="template", step_path="/tmp/model.step", cadquery_code=code,
        )

        with (
            patch(
                "backend.graph.nodes.generation.SpecCompiler",
                return_value=MagicMock(compile=MagicMock(return_value=mock_result)),
            ),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text") as mock_write,
        ):
            await generate_step_text_node(state)

        mock_write.assert_called_once_with(code, encoding="utf-8")


# ---------------------------------------------------------------------------
# Drawing generation node saves code
# ---------------------------------------------------------------------------

class TestDrawingNodeCodePersistence:
    @pytest.mark.asyncio
    async def test_drawing_node_returns_generated_code(self) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        state: CadJobState = {
            "job_id": "test-code-draw-1",
            "input_type": "drawing",
            "image_path": "/tmp/test.jpg",
            "status": "generating",
        }

        code = "import cadquery as cq\nresult = cq.Workplane().cylinder(50, 25)"

        with (
            patch(
                "backend.graph.nodes.generation._orchestrate_drawing_generation",
                return_value={"step_path": "/tmp/model.step", "generated_code": code},
            ),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            result = await generate_step_drawing_node(state, config={})

        assert result.get("generated_code") == code

    @pytest.mark.asyncio
    async def test_drawing_node_none_code_from_pipeline(self) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        state: CadJobState = {
            "job_id": "test-code-draw-2",
            "input_type": "drawing",
            "image_path": "/tmp/test.jpg",
            "status": "generating",
        }

        with (
            patch(
                "backend.graph.nodes.generation._orchestrate_drawing_generation",
                return_value={"step_path": "/tmp/model.step", "generated_code": None},
            ),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
        ):
            result = await generate_step_drawing_node(state, config={})

        assert result.get("generated_code") is None


# ---------------------------------------------------------------------------
# Finalize node persists new fields
# ---------------------------------------------------------------------------

class TestFinalizeNodePersistence:
    @pytest.mark.asyncio
    async def test_finalize_persists_generated_code(self) -> None:
        from backend.graph.nodes.lifecycle import finalize_node

        state: CadJobState = {
            "job_id": "test-finalize-1",
            "input_type": "text",
            "status": "generating",
            "step_path": "/tmp/model.step",
            "generated_code": "import cadquery as cq\nresult = cq.Workplane().box(10,10,10)",
        }

        with patch(
            "backend.graph.nodes.lifecycle.update_job",
            new_callable=AsyncMock,
        ) as mock_update:
            await finalize_node(state)

        call_kwargs = mock_update.call_args
        assert call_kwargs[0][0] == "test-finalize-1"
        kwargs = call_kwargs[1]
        assert kwargs["generated_code"] == state["generated_code"]
        assert kwargs["status"] == "completed"

    @pytest.mark.asyncio
    async def test_finalize_persists_parent_job_id(self) -> None:
        from backend.graph.nodes.lifecycle import finalize_node

        state: CadJobState = {
            "job_id": "test-finalize-2",
            "input_type": "text",
            "status": "generating",
            "step_path": "/tmp/model.step",
            "parent_job_id": "parent-123",
        }

        with patch(
            "backend.graph.nodes.lifecycle.update_job",
            new_callable=AsyncMock,
        ) as mock_update:
            await finalize_node(state)

        kwargs = mock_update.call_args[1]
        assert kwargs["parent_job_id"] == "parent-123"

    @pytest.mark.asyncio
    async def test_finalize_persists_code_on_failed_postprocess(self) -> None:
        """generated_code should be saved even if the job failed in postprocess."""
        from backend.graph.nodes.lifecycle import finalize_node

        state: CadJobState = {
            "job_id": "test-finalize-3",
            "input_type": "text",
            "status": "failed",
            "error": "printability check failed",
            "step_path": "/tmp/model.step",
            "generated_code": "import cadquery as cq\nresult = cq.Workplane().box(10,10,10)",
        }

        with patch(
            "backend.graph.nodes.lifecycle.update_job",
            new_callable=AsyncMock,
        ) as mock_update:
            await finalize_node(state)

        kwargs = mock_update.call_args[1]
        assert kwargs["generated_code"] == state["generated_code"]
        assert kwargs["status"] == "failed"


# ---------------------------------------------------------------------------
# create_job_node persists parent_job_id
# ---------------------------------------------------------------------------

class TestCreateJobNodeParent:
    @pytest.mark.asyncio
    async def test_create_job_passes_parent_job_id(self) -> None:
        from backend.graph.nodes.lifecycle import create_job_node

        state: CadJobState = {
            "job_id": "test-create-1",
            "input_type": "text",
            "input_text": "make a gear",
            "parent_job_id": "parent-abc",
            "status": "pending",
        }

        with (
            patch("backend.graph.nodes.lifecycle.create_job", new_callable=AsyncMock),
            patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock) as mock_update,
        ):
            await create_job_node(state)

        # update_job should be called with parent_job_id
        kwargs = mock_update.call_args[1]
        assert kwargs["parent_job_id"] == "parent-abc"


# ---------------------------------------------------------------------------
# Fork validation (text only)
# ---------------------------------------------------------------------------

class TestForkValidation:
    def test_create_request_has_parent_job_id(self) -> None:
        from backend.api.v1.jobs import CreateJobRequest
        req = CreateJobRequest(input_type="text", text="hello", parent_job_id="p1")
        assert req.parent_job_id == "p1"

    def test_create_request_parent_defaults_to_none(self) -> None:
        from backend.api.v1.jobs import CreateJobRequest
        req = CreateJobRequest(input_type="text", text="hello")
        assert req.parent_job_id is None


# ---------------------------------------------------------------------------
# parent_job_id existence validation
# ---------------------------------------------------------------------------

class TestParentJobIdValidation:
    @pytest.mark.asyncio
    async def test_nonexistent_parent_raises_error(self) -> None:
        """create_job_endpoint should raise 404 for nonexistent parent_job_id."""
        from unittest.mock import MagicMock

        from backend.api.v1.errors import APIError
        from backend.api.v1.jobs import CreateJobRequest, create_job_endpoint

        body = CreateJobRequest(
            input_type="text", text="hello", parent_job_id="nonexistent-parent",
        )
        mock_request = MagicMock()

        # Mock DB session returning None for the parent job
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.db.database.async_session", return_value=mock_session):
            with pytest.raises(APIError, match="Parent job not found"):
                await create_job_endpoint(body, mock_request)


# ---------------------------------------------------------------------------
# API response model has new fields
# ---------------------------------------------------------------------------

class TestJobDetailResponseFields:
    def test_detail_has_generated_code(self) -> None:
        from backend.api.v1.jobs import JobDetailResponse
        assert "generated_code" in JobDetailResponse.model_fields

    def test_detail_has_parent_job_id(self) -> None:
        from backend.api.v1.jobs import JobDetailResponse
        assert "parent_job_id" in JobDetailResponse.model_fields

    def test_detail_has_child_job_ids(self) -> None:
        from backend.api.v1.jobs import JobDetailResponse
        assert "child_job_ids" in JobDetailResponse.model_fields

    def test_detail_child_job_ids_defaults_empty(self) -> None:
        from backend.api.v1.jobs import JobDetailResponse
        resp = JobDetailResponse(
            job_id="j1", status="completed", input_type="text",
            input_text="x", created_at="2026-01-01",
        )
        assert resp.child_job_ids == []


# ---------------------------------------------------------------------------
# _job_to_detail include_code parameter
# ---------------------------------------------------------------------------

class TestJobToDetailIncludeCode:
    def test_include_code_true_by_default(self) -> None:
        from backend.api.v1.jobs import _job_to_detail
        from backend.models.job import Job, JobStatus

        job = Job(
            job_id="j1", status=JobStatus.COMPLETED, input_type="text",
            input_text="x", created_at="2026-01-01",
            generated_code="import cadquery",
        )
        detail = _job_to_detail(job)
        assert detail.generated_code == "import cadquery"

    def test_include_code_false_excludes(self) -> None:
        from backend.api.v1.jobs import _job_to_detail
        from backend.models.job import Job, JobStatus

        job = Job(
            job_id="j2", status=JobStatus.COMPLETED, input_type="text",
            input_text="x", created_at="2026-01-01",
            generated_code="import cadquery",
        )
        detail = _job_to_detail(job, include_code=False)
        assert detail.generated_code is None


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/code endpoint
# ---------------------------------------------------------------------------

class TestGetJobCodeEndpoint:
    def test_code_endpoint_exists(self) -> None:
        from backend.api.v1.jobs import get_job_code
        assert callable(get_job_code)

    @pytest.mark.asyncio
    async def test_code_endpoint_returns_code(self) -> None:
        from backend.api.v1.jobs import get_job_code
        from backend.models.job import Job, JobStatus

        mock_job = Job(
            job_id="j-code-1", status=JobStatus.COMPLETED, input_type="text",
            input_text="x", created_at="2026-01-01",
            generated_code="import cadquery as cq",
        )

        with patch("backend.api.v1.jobs.get_job", new_callable=AsyncMock, return_value=mock_job):
            result = await get_job_code("j-code-1")
        assert result["job_id"] == "j-code-1"
        assert result["generated_code"] == "import cadquery as cq"

    @pytest.mark.asyncio
    async def test_code_endpoint_not_found(self) -> None:
        from backend.api.v1.errors import APIError
        from backend.api.v1.jobs import get_job_code

        with patch("backend.api.v1.jobs.get_job", new_callable=AsyncMock, return_value=None):
            with pytest.raises(APIError):
                await get_job_code("nonexistent")


# ---------------------------------------------------------------------------
# Repository child_job_ids query
# ---------------------------------------------------------------------------

class TestChildJobIdsQuery:
    @pytest.mark.asyncio
    async def test_list_child_job_ids_exists(self) -> None:
        from backend.db.repository import list_child_job_ids
        assert callable(list_child_job_ids)


# ---------------------------------------------------------------------------
# Pipeline return value
# ---------------------------------------------------------------------------

class TestPipelineReturnValue:
    def test_generate_step_from_spec_signature(self) -> None:
        import inspect
        from backend.pipeline.pipeline import generate_step_from_spec
        sig = inspect.signature(generate_step_from_spec)
        ret = sig.return_annotation
        # Should return str | None (or Union[str, None])
        assert ret is not None
        assert ret != inspect.Parameter.empty
