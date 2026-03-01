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
            "analyze_intent", "analyze_vision", "stub_organic",
            "confirm_with_user",
            "generate_step_text", "generate_step_drawing",
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


class TestGraphExports:
    def test_imports_from_package(self) -> None:
        from backend.graph import build_graph, get_compiled_graph
        assert callable(build_graph)
        assert callable(get_compiled_graph)
