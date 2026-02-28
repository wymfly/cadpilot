"""Tests for postprocess graph nodes."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.graph.state import CadJobState


class TestConvertPreviewNode:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from backend.graph.nodes.postprocess import convert_preview_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path="/outputs/t1/model.step",
        )
        with patch(
            "backend.graph.nodes.postprocess._convert_step_to_glb",
            return_value="/outputs/t1/model.glb",
        ):
            result = await convert_preview_node(state)

        assert result["model_url"] is not None
        assert "model.glb" in result["model_url"]

    @pytest.mark.asyncio
    async def test_failure_is_non_fatal(self) -> None:
        from backend.graph.nodes.postprocess import convert_preview_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path="/outputs/t1/model.step",
        )
        with patch(
            "backend.graph.nodes.postprocess._convert_step_to_glb",
            side_effect=Exception("GLB conversion failed"),
        ):
            result = await convert_preview_node(state)

        # Non-fatal: model_url None, but no "failed" status
        assert result.get("model_url") is None
        assert "status" not in result or result.get("status") != "failed"

    @pytest.mark.asyncio
    async def test_skips_if_no_step_path(self) -> None:
        from backend.graph.nodes.postprocess import convert_preview_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path=None,
        )
        result = await convert_preview_node(state)
        assert result == {}


class TestCheckPrintabilityNode:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        from backend.graph.nodes.postprocess import check_printability_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path="/outputs/t1/model.step",
        )
        mock_result = {"score": 0.92, "issues": []}
        with patch(
            "backend.graph.nodes.postprocess._run_printability_check",
            return_value=mock_result,
        ):
            result = await check_printability_node(state)

        assert result["printability"] == mock_result

    @pytest.mark.asyncio
    async def test_failure_is_non_fatal(self) -> None:
        from backend.graph.nodes.postprocess import check_printability_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path="/outputs/t1/model.step",
        )
        with patch(
            "backend.graph.nodes.postprocess._run_printability_check",
            side_effect=Exception("Analysis error"),
        ):
            result = await check_printability_node(state)

        assert result.get("printability") is None
        assert "status" not in result or result.get("status") != "failed"

    @pytest.mark.asyncio
    async def test_skips_if_no_step_path(self) -> None:
        from backend.graph.nodes.postprocess import check_printability_node

        state = CadJobState(
            job_id="t1", input_type="text", status="generating",
            step_path=None,
        )
        result = await check_printability_node(state)
        assert result == {}
