"""Integration tests for HITL interrupt/resume via LangGraph.

These tests verify the full interrupt/resume cycle of the compiled
CadJob StateGraph:

1. Text path: create → analyze_intent → interrupt → confirm → generate → postprocess → finalize
2. Drawing path: create → analyze_vision → interrupt → confirm → generate → postprocess → finalize

All DB calls are mocked (no real database needed).  The graph uses
``MemorySaver`` for lightweight in-memory checkpointing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.types import Command

from backend.core.spec_compiler import CompileResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lifecycle_patches():
    """Return context-manager patches for all DB-touching lifecycle helpers."""
    return (
        patch("backend.graph.nodes.lifecycle.create_job", new_callable=AsyncMock),
        patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock),
        patch("backend.graph.nodes.analysis._safe_update_job", new_callable=AsyncMock),
    )


# ---------------------------------------------------------------------------
# Text path
# ---------------------------------------------------------------------------

class TestHitlTextPath:
    """Test the full text path: create → analyze_intent → interrupt → confirm → generate → postprocess → finalize."""

    @pytest.mark.asyncio
    async def test_first_run_interrupts_before_confirm(self) -> None:
        """Graph should stop at interrupt_before=['confirm_with_user'] and
        the last state should carry the intent + awaiting_confirmation status.
        """
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()  # MemorySaver
        config = {"configurable": {"thread_id": "hitl-text-1"}}

        initial = {
            "job_id": "hitl-text-1",
            "input_type": "text",
            "input_text": "make a 50mm gear",
            "status": "pending",
        }

        mock_intent = {"description": "gear", "parameters": {"diameter": 50}}

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._parse_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
        ):
            result = await graph.ainvoke(initial, config=config)

        # After interrupt, status should be awaiting_confirmation
        assert result["status"] == "awaiting_confirmation"
        assert result["intent"] == mock_intent

    @pytest.mark.asyncio
    async def test_resume_after_confirm_completes(self) -> None:
        """After resume with Command, graph should run through generate → postprocess → finalize."""
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-text-2"}}

        initial = {
            "job_id": "hitl-text-2",
            "input_type": "text",
            "input_text": "make a gear",
            "status": "pending",
        }

        mock_intent = {"description": "gear", "parameters": {"diameter": 50}}

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._parse_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "backend.graph.nodes.generation.SpecCompiler",
                return_value=MagicMock(compile=MagicMock(return_value=CompileResult(method="template", step_path="/tmp/model.step"))),
            ),
            patch(
                "backend.graph.nodes.postprocess._convert_step_to_glb",
                return_value="/tmp/model.glb",
            ),
            patch(
                "backend.graph.nodes.postprocess._run_printability_check",
                return_value={"score": 0.9},
            ),
        ):
            # First run — interrupts before confirm_with_user
            result1 = await graph.ainvoke(initial, config=config)
            assert result1["status"] == "awaiting_confirmation"

            # Resume with confirmed params
            result2 = await graph.ainvoke(
                Command(resume={
                    "confirmed_params": {"diameter": 50},
                    "disclaimer_accepted": True,
                }),
                config=config,
            )

        # After full cycle, finalize should set terminal status
        assert result2["status"] in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_resume_preserves_intent_through_graph(self) -> None:
        """Intent parsed in phase 1 should be available in state after resume."""
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-text-3"}}

        initial = {
            "job_id": "hitl-text-3",
            "input_type": "text",
            "input_text": "make a 30mm bolt",
            "status": "pending",
        }

        mock_intent = {"description": "bolt", "parameters": {"diameter": 30, "length": 60}}

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._parse_intent",
                new_callable=AsyncMock,
                return_value=mock_intent,
            ),
            patch(
                "backend.graph.nodes.generation.SpecCompiler",
                return_value=MagicMock(compile=MagicMock(return_value=CompileResult(method="template", step_path="/tmp/bolt.step"))),
            ),
            patch(
                "backend.graph.nodes.postprocess._convert_step_to_glb",
                return_value="/tmp/bolt.glb",
            ),
            patch(
                "backend.graph.nodes.postprocess._run_printability_check",
                return_value={"score": 0.95},
            ),
        ):
            await graph.ainvoke(initial, config=config)

            result = await graph.ainvoke(
                Command(resume={
                    "confirmed_params": {"diameter": 30, "length": 60},
                    "disclaimer_accepted": True,
                }),
                config=config,
            )

        # Intent from phase 1 should still be in the final state
        assert result["intent"] == mock_intent


# ---------------------------------------------------------------------------
# Drawing path
# ---------------------------------------------------------------------------

class TestHitlDrawingPath:
    """Test the drawing path: create → analyze_vision → interrupt → confirm → generate → postprocess → finalize."""

    @pytest.mark.asyncio
    async def test_drawing_interrupts_with_spec(self) -> None:
        """First run on drawing path should interrupt with drawing_spec populated."""
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-drawing-1"}}

        initial = {
            "job_id": "hitl-drawing-1",
            "input_type": "drawing",
            "image_path": "/tmp/test.jpg",
            "status": "pending",
        }

        mock_spec = {"part_type": "rotational", "diameter": 30}

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._run_analyze_vision",
                return_value=(mock_spec, "reasoning text"),
            ),
        ):
            result = await graph.ainvoke(initial, config=config)

        assert result["status"] == "awaiting_drawing_confirmation"
        assert result["drawing_spec"] == mock_spec

    @pytest.mark.asyncio
    async def test_drawing_resume_completes(self) -> None:
        """Resume on drawing path should complete through finalize."""
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-drawing-2"}}

        initial = {
            "job_id": "hitl-drawing-2",
            "input_type": "drawing",
            "image_path": "/tmp/test.jpg",
            "status": "pending",
        }

        mock_spec = {"part_type": "rotational", "diameter": 30}

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._run_analyze_vision",
                return_value=(mock_spec, "reasoning text"),
            ),
            patch("backend.graph.nodes.generation._run_generate_from_spec"),
            patch(
                "backend.graph.nodes.postprocess._convert_step_to_glb",
                return_value="/tmp/model.glb",
            ),
            patch(
                "backend.graph.nodes.postprocess._run_printability_check",
                return_value={"score": 0.85},
            ),
        ):
            # Phase 1 — interrupt
            result1 = await graph.ainvoke(initial, config=config)
            assert result1["status"] == "awaiting_drawing_confirmation"

            # Phase 2 — resume with confirmed spec
            result2 = await graph.ainvoke(
                Command(resume={
                    "confirmed_spec": mock_spec,
                    "disclaimer_accepted": True,
                }),
                config=config,
            )

        assert result2["status"] in ("completed", "failed")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestHitlEdgeCases:
    """Edge cases: analysis failure + interrupt, organic path."""

    @pytest.mark.asyncio
    async def test_analysis_failure_still_interrupts(self) -> None:
        """Even when analysis fails, graph should still interrupt before confirm.

        This is by design — the interrupt_before is unconditional.  After resume,
        the confirm node executes, then route_after_confirm sees status='failed'
        and routes to finalize.
        """
        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-fail-1"}}

        initial = {
            "job_id": "hitl-fail-1",
            "input_type": "text",
            "input_text": "make something",
            "status": "pending",
        }

        p1, p2, p3 = _lifecycle_patches()
        with (
            p1, p2, p3,
            patch(
                "backend.graph.nodes.analysis._parse_intent",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM unavailable"),
            ),
        ):
            result = await graph.ainvoke(initial, config=config)

        # Analysis failed, so status should be 'failed' at interrupt point
        assert result["status"] == "failed"
        assert result["failure_reason"] == "generation_error"

    @pytest.mark.asyncio
    async def test_organic_path_interrupts(self) -> None:
        """Organic path goes through analyze_organic → interrupt before confirm."""
        from unittest.mock import MagicMock

        from backend.graph import get_compiled_graph

        graph = await get_compiled_graph()
        config = {"configurable": {"thread_id": "hitl-organic-1"}}

        initial = {
            "job_id": "hitl-organic-1",
            "input_type": "organic",
            "input_text": "a dragon sculpture",
            "status": "pending",
        }

        mock_spec = MagicMock()
        mock_spec.model_dump.return_value = {"prompt_en": "a dragon sculpture"}

        mock_builder = MagicMock()
        mock_builder.build = AsyncMock(return_value=mock_spec)

        p1, p2, p3 = _lifecycle_patches()
        p4 = patch("backend.graph.nodes.organic._safe_update_job", new_callable=AsyncMock)
        p5 = patch("backend.graph.nodes.organic.OrganicSpecBuilder", return_value=mock_builder)
        with p1, p2, p3, p4, p5:
            result = await graph.ainvoke(initial, config=config)

        assert result["status"] == "awaiting_confirmation"
