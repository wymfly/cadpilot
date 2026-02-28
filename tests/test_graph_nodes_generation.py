"""Tests for generation graph nodes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.graph.state import CadJobState


class TestGenerateStepTextNode:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state = CadJobState(
            job_id="t1", input_type="text", status="confirmed",
            confirmed_params={"diameter": 50}, matched_template="gear_spur",
        )
        with patch(
            "backend.graph.nodes.generation._run_template_generation",
            return_value="/outputs/t1/model.step",
        ):
            result = await generate_step_text_node(state)

        assert result["step_path"] == "/outputs/t1/model.step"
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
        assert result == {}

    @pytest.mark.asyncio
    async def test_error_returns_failed(self) -> None:
        from backend.graph.nodes.generation import generate_step_text_node

        state = CadJobState(
            job_id="t1", input_type="text", status="confirmed",
            confirmed_params={"diameter": 50},
        )
        with patch(
            "backend.graph.nodes.generation._run_template_generation",
            side_effect=RuntimeError("Sandbox failure"),
        ):
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
        with patch("backend.graph.nodes.generation._run_generate_from_spec") as mock_gen:
            result = await generate_step_drawing_node(state)

        mock_gen.assert_called_once()
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
        assert result == {}

    @pytest.mark.asyncio
    async def test_error_returns_failed(self) -> None:
        from backend.graph.nodes.generation import generate_step_drawing_node

        state = CadJobState(
            job_id="t1", input_type="drawing", status="confirmed",
            image_path="/tmp/test.jpg",
            confirmed_spec={"part_type": "rotational"},
        )
        with patch(
            "backend.graph.nodes.generation._run_generate_from_spec",
            side_effect=RuntimeError("CadQuery execution failed"),
        ):
            result = await generate_step_drawing_node(state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "generation_error"
