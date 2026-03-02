"""Tests for the compiled CadJob StateGraph."""

from __future__ import annotations

import pytest


class TestBuildGraph:
    def test_compile_succeeds(self) -> None:
        from backend.graph.builder import build_graph
        graph = build_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self) -> None:
        from backend.graph.builder import build_graph
        graph = build_graph()
        node_names = set(graph.nodes.keys())
        expected = {
            "create_job",
            "analyze_intent", "analyze_vision", "analyze_organic",
            "confirm_with_user",
            "generate_step_text", "generate_step_drawing",
            "generate_organic_mesh", "postprocess_organic",
            "convert_preview", "check_printability",
            "finalize",
        }
        assert expected.issubset(node_names), f"Missing: {expected - node_names}"


class TestGetCompiledGraph:
    @pytest.mark.asyncio
    async def test_compiles_with_memory_saver(self) -> None:
        from backend.graph.builder import get_compiled_graph
        graph = await get_compiled_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_compiled_graph_has_checkpointer(self) -> None:
        from backend.graph.builder import get_compiled_graph
        graph = await get_compiled_graph()
        assert graph.checkpointer is not None


class TestGraphExports:
    def test_imports_from_package(self) -> None:
        from backend.graph import build_graph, get_compiled_graph
        assert callable(build_graph)
        assert callable(get_compiled_graph)


class TestTraceMerge:
    """_wrap_node merges ctx._fallback_trace into trace entry."""

    @pytest.mark.asyncio
    async def test_fallback_trace_merged_into_node_trace(self):
        from backend.graph.builder_new import PipelineBuilder
        from backend.graph.descriptor import NodeDescriptor

        async def node_with_fallback(ctx):
            # Simulate execute_with_fallback writing trace
            ctx._fallback_trace = {
                "fallback_triggered": True,
                "strategy_used": "neural",
                "strategies_attempted": [
                    {"name": "algorithm", "error": "failed"},
                    {"name": "neural", "result": "success"},
                ],
            }

        desc = NodeDescriptor(
            name="test_trace", display_name="Trace Test", fn=node_with_fallback,
        )
        builder = PipelineBuilder()
        wrapped = builder._wrap_node(desc)

        state = {
            "job_id": "j1", "input_type": "text",
            "assets": {}, "data": {},
            "pipeline_config": {}, "node_trace": [],
        }
        result = await wrapped(state)

        traces = result["node_trace"]
        assert len(traces) == 1
        entry = traces[0]
        assert entry["node"] == "test_trace"
        assert entry["fallback_triggered"] is True
        assert entry["strategy_used"] == "neural"
        assert len(entry["strategies_attempted"]) == 2
