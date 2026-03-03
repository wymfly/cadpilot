"""Tests for generation graph nodes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.spec_compiler import CompilationError, CompileResult
from backend.graph.state import CadJobState


class TestGenerateStepTextNode:
    @pytest.fixture
    def base_state(self):
        return CadJobState(
            job_id="t1",
            input_type="text",
            input_text="生成一个圆柱体",
            status="confirmed",
            matched_template="cylinder_simple",
            confirmed_params={"diameter": 50, "height": 100},
            token_stats={"stages": []},
        )

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.SpecCompiler")
    async def test_template_path(self, MockCompiler, base_state) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        compiler = MockCompiler.return_value
        compiler.compile.return_value = CompileResult(
            method="template", template_name="cylinder_simple", step_path="/tmp/model.step"
        )
        result = await generate_step_text_node(base_state)
        assert result["step_path"] == "/tmp/model.step"
        assert result["status"] == "generating"
        compiler.compile.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.SpecCompiler")
    async def test_llm_fallback_path(self, MockCompiler, base_state) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        base_state["matched_template"] = None
        compiler = MockCompiler.return_value
        compiler.compile.return_value = CompileResult(
            method="llm_fallback", step_path="/tmp/model.step"
        )
        result = await generate_step_text_node(base_state)
        assert result["step_path"] == "/tmp/model.step"
        assert result["status"] == "generating"

    @pytest.mark.asyncio
    async def test_idempotent_skips_if_step_exists(self, tmp_path) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        step_file = tmp_path / "model.step"
        step_file.write_text("solid")
        state = CadJobState(
            job_id="t1", input_type="text", status="confirmed",
            step_path=str(step_file),
        )
        result = await generate_step_text_node(state)
        assert "step_path" not in result  # idempotent skip
        assert result.get("_reasoning", {}).get("skip")

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.SpecCompiler")
    async def test_both_fail(self, MockCompiler, base_state) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        compiler = MockCompiler.return_value
        compiler.compile.side_effect = CompilationError("all failed")
        result = await generate_step_text_node(base_state)
        assert result["status"] == "failed"
        assert "all failed" in result["error"]

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.SpecCompiler")
    async def test_error_returns_failed(self, MockCompiler) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state = CadJobState(
            job_id="t1", input_type="text", status="confirmed",
            confirmed_params={"diameter": 50},
        )
        compiler = MockCompiler.return_value
        compiler.compile.side_effect = RuntimeError("Sandbox failure")
        result = await generate_step_text_node(state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "generation_error"


class TestGenerateStepDrawingNode:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        state = CadJobState(
            job_id="t1", input_type="drawing", status="confirmed",
            image_path="/tmp/test.jpg",
            confirmed_spec={"part_type": "rotational"},
        )
        mock_orch = AsyncMock(return_value={"step_path": "/tmp/model.step", "generated_code": "x=1"})
        with (
            patch("backend.graph.nodes.generation._orchestrate_drawing_generation", mock_orch),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
            patch("pathlib.Path.write_text"),
        ):
            result = await generate_step_drawing_node(state, config={})

        mock_orch.assert_awaited_once()
        assert result["status"] == "generating"
        assert "step_path" in result

    @pytest.mark.asyncio
    async def test_idempotent_skips_if_step_exists(self, tmp_path) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        step_file = tmp_path / "model.step"
        step_file.write_text("solid")
        state = CadJobState(
            job_id="t1", input_type="drawing", status="confirmed",
            step_path=str(step_file),
        )
        result = await generate_step_drawing_node(state)
        assert "step_path" not in result  # idempotent skip
        assert result.get("_reasoning", {}).get("skip")

    @pytest.mark.asyncio
    async def test_error_returns_failed(self) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        state = CadJobState(
            job_id="t1", input_type="drawing", status="confirmed",
            image_path="/tmp/test.jpg",
            confirmed_spec={"part_type": "rotational"},
        )
        mock_orch = AsyncMock(side_effect=RuntimeError("CadQuery execution failed"))
        with (
            patch("backend.graph.nodes.generation._orchestrate_drawing_generation", mock_orch),
            patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock),
            patch("pathlib.Path.mkdir"),
        ):
            result = await generate_step_drawing_node(state, config={})

        assert result["status"] == "failed"
        assert result["failure_reason"] == "generation_error"
