"""Tests for generation node LCEL migration (T4)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(job_id="test-job", image_path="/tmp/test.png", spec=None):
    """Build a minimal CadJobState dict for generation tests."""
    return {
        "job_id": job_id,
        "image_path": image_path,
        "confirmed_spec": spec or {"part_type": "rotational", "overall_dimensions": {"max_diameter": 50}, "base_body": {"method": "revolve", "profile": [{"diameter": 50, "height": 30}]}, "features": [], "notes": []},
        "drawing_spec": None,
        "step_path": None,
    }


def _make_config(best_of_n=1, max_refinements=2):
    """Build a config dict with pipeline_config."""
    from backend.models.pipeline_config import PipelineConfig
    pc = PipelineConfig(best_of_n=best_of_n, max_refinements=max_refinements)
    return {"configurable": {"pipeline_config": pc}}


# ---------------------------------------------------------------------------
# _orchestrate_drawing_generation tests
# ---------------------------------------------------------------------------

class TestOrchestrateDrawingGeneration:

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.build_refiner_subgraph")
    @patch("backend.graph.nodes.generation.build_code_gen_chain")
    @patch("backend.graph.nodes.generation.ModelingStrategist")
    async def test_single_path_happy(self, mock_strat_cls, mock_codegen_fn, mock_refiner_fn, tmp_path):
        """Single-path: strategy → codegen → execute → refine → return."""
        from backend.graph.nodes.generation import _orchestrate_drawing_generation

        step_path = str(tmp_path / "model.step")

        # Strategy
        mock_ctx = MagicMock()
        mock_ctx.to_prompt_text.return_value = "build a cylinder"
        mock_ctx.strategy = "revolve strategy"
        mock_strat_cls.return_value.select.return_value = mock_ctx

        # Codegen chain returns code (no $output_filename template var)
        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = "result = 'hello'"
        mock_codegen_fn.return_value = mock_chain

        # SafeExecutor — patch at module level
        with patch("backend.graph.nodes.generation.SafeExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(success=True)

            # Refiner subgraph
            mock_refiner = AsyncMock()
            mock_refiner.ainvoke.return_value = {"code": "result = 'refined'", "step_path": step_path}
            mock_refiner_fn.return_value = mock_refiner

            # Geometry validation
            with patch("backend.graph.nodes.generation.validate_step_geometry") as mock_geo:
                mock_geo.return_value = MagicMock(is_valid=True, volume=100, bbox=(50, 50, 30))

                state = {**_make_state(), "step_path": step_path}
                config = _make_config()
                result = await _orchestrate_drawing_generation(state, config)

        assert result["step_path"] == step_path
        assert result.get("generated_code") is not None
        mock_chain.ainvoke.assert_awaited_once()
        mock_refiner.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.build_refiner_subgraph")
    @patch("backend.graph.nodes.generation.build_code_gen_chain")
    @patch("backend.graph.nodes.generation.ModelingStrategist")
    async def test_codegen_returns_none(self, mock_strat_cls, mock_codegen_fn, mock_refiner_fn, tmp_path):
        """When codegen returns None, orchestrator returns failure."""
        from backend.graph.nodes.generation import _orchestrate_drawing_generation

        mock_ctx = MagicMock()
        mock_ctx.to_prompt_text.return_value = "ctx"
        mock_ctx.strategy = "s"
        mock_strat_cls.return_value.select.return_value = mock_ctx

        mock_chain = AsyncMock()
        mock_chain.ainvoke.return_value = None
        mock_codegen_fn.return_value = mock_chain

        state = {**_make_state(), "step_path": str(tmp_path / "m.step")}
        result = await _orchestrate_drawing_generation(state, _make_config())

        assert result["status"] == "failed"
        assert "generation_error" in result.get("failure_reason", "")

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.build_refiner_subgraph")
    @patch("backend.graph.nodes.generation.build_code_gen_chain")
    @patch("backend.graph.nodes.generation.ModelingStrategist")
    async def test_best_of_n_picks_highest_score(self, mock_strat_cls, mock_codegen_fn, mock_refiner_fn, tmp_path):
        """Best-of-N: picks candidate with highest geometry score."""
        from backend.graph.nodes.generation import _orchestrate_drawing_generation

        step_path = str(tmp_path / "model.step")

        mock_ctx = MagicMock()
        mock_ctx.to_prompt_text.return_value = "ctx"
        mock_ctx.strategy = "s"
        mock_strat_cls.return_value.select.return_value = mock_ctx

        # 3 candidates: second is best
        mock_chain = AsyncMock()
        mock_chain.ainvoke.side_effect = ["code_a", "code_b", "code_c"]
        mock_codegen_fn.return_value = mock_chain

        with patch("backend.graph.nodes.generation.SafeExecutor") as mock_exec_cls:
            mock_exec_cls.return_value.execute.return_value = MagicMock(success=True)

            # Score: a=0.5, b=0.9, c=0.3
            with patch("backend.graph.nodes.generation._score_geometry") as mock_score:
                mock_score.side_effect = [
                    (True, True, False, False),   # a
                    (True, True, True, True),      # b
                    (True, False, False, False),   # c
                ]
                with patch("backend.graph.nodes.generation.score_candidate") as mock_sc:
                    mock_sc.side_effect = [0.5, 0.9, 0.3]

                    mock_refiner = AsyncMock()
                    mock_refiner.ainvoke.return_value = {"code": "code_b", "step_path": step_path}
                    mock_refiner_fn.return_value = mock_refiner

                    with patch("backend.graph.nodes.generation.validate_step_geometry") as mock_geo:
                        mock_geo.return_value = MagicMock(is_valid=True)

                        state = {**_make_state(), "step_path": step_path}
                        config = _make_config(best_of_n=3)
                        result = await _orchestrate_drawing_generation(state, config)

        assert result.get("generated_code") is not None
        assert mock_chain.ainvoke.await_count == 3


# ---------------------------------------------------------------------------
# generate_step_drawing_node tests
# ---------------------------------------------------------------------------

class TestGenerateStepDrawingNode:

    @pytest.mark.asyncio
    async def test_idempotent_skip(self, tmp_path):
        """Node skips if step_path already exists."""
        from backend.graph.nodes.generation import generate_step_drawing_node

        step_file = tmp_path / "model.step"
        step_file.write_text("existing")

        state = _make_state()
        state["step_path"] = str(step_file)
        result = await generate_step_drawing_node(state)
        assert "skip" in str(result.get("_reasoning", {}))

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation._orchestrate_drawing_generation")
    @patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock)
    async def test_timeout_returns_failure(self, mock_dispatch, mock_orch, tmp_path):
        """300s timeout triggers failure status."""
        from backend.graph.nodes.generation import generate_step_drawing_node, OUTPUTS_DIR

        # Make orchestrator hang
        async def _hang(state, config):
            await asyncio.sleep(999)

        mock_orch.side_effect = _hang

        with patch.object(Path, "mkdir"):
            with patch("backend.graph.nodes.generation.OUTPUTS_DIR", tmp_path):
                state = _make_state()
                state["image_path"] = "/tmp/test.png"
                # Use a very short timeout for test speed
                with patch("backend.graph.nodes.generation.GENERATION_TIMEOUT_S", 0.1):
                    result = await generate_step_drawing_node(state, config={})

        assert result["status"] == "failed"
        assert "timeout" in result.get("failure_reason", "")

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation._orchestrate_drawing_generation")
    @patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock)
    async def test_no_image_path_returns_failure(self, mock_dispatch, mock_orch, tmp_path):
        """Missing image_path returns failure without calling orchestrator."""
        from backend.graph.nodes.generation import generate_step_drawing_node

        with patch("backend.graph.nodes.generation.OUTPUTS_DIR", tmp_path):
            state = _make_state()
            state["image_path"] = None
            result = await generate_step_drawing_node(state)

        assert result["status"] == "failed"
        mock_orch.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation._orchestrate_drawing_generation")
    @patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock)
    async def test_success_persists_code(self, mock_dispatch, mock_orch, tmp_path):
        """On success, code is written to job_dir/code.py."""
        from backend.graph.nodes.generation import generate_step_drawing_node

        step_path = str(tmp_path / "test-job" / "model.step")
        mock_orch.return_value = {"step_path": step_path, "generated_code": "x = 1"}

        with patch("backend.graph.nodes.generation.OUTPUTS_DIR", tmp_path):
            state = _make_state()
            result = await generate_step_drawing_node(state, config={})

        assert result["status"] == "generating"
        code_file = tmp_path / "test-job" / "code.py"
        assert code_file.exists()
        assert code_file.read_text() == "x = 1"
