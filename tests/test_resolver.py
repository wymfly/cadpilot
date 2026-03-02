"""Tests for DependencyResolver — topological sorting, OR deps, conflicts, terminal."""

import pytest

from backend.graph.descriptor import NodeDescriptor
from backend.graph.registry import NodeRegistry
from backend.graph.resolver import DependencyResolver


def _desc(name, **kw):
    async def fn(ctx):
        pass
    defaults = dict(name=name, display_name=name, fn=fn)
    defaults.update(kw)
    return NodeDescriptor(**defaults)


def _build_registry(*descs):
    reg = NodeRegistry()
    for d in descs:
        reg.register(d)
    return reg


# ---------------------------------------------------------------------------
# Basic resolution
# ---------------------------------------------------------------------------

class TestBasicResolution:
    def test_empty_registry(self):
        reg = _build_registry()
        result = DependencyResolver.resolve(reg, {})
        assert result.ordered_nodes == []

    def test_single_node(self):
        reg = _build_registry(_desc("only", produces=["x"]))
        result = DependencyResolver.resolve(reg, {})
        assert len(result.ordered_nodes) == 1
        assert result.ordered_nodes[0].name == "only"

    def test_linear_chain(self):
        reg = _build_registry(
            _desc("a", produces=["x"]),
            _desc("b", requires=["x"], produces=["y"]),
            _desc("c", requires=["y"]),
        )
        result = DependencyResolver.resolve(reg, {})
        names = [d.name for d in result.ordered_nodes]
        assert names == ["a", "b", "c"]

    def test_diamond_dependency(self):
        reg = _build_registry(
            _desc("root", produces=["x"]),
            _desc("left", requires=["x"], produces=["y1"]),
            _desc("right", requires=["x"], produces=["y2"]),
            _desc("merge", requires=["y1", "y2"]),
        )
        result = DependencyResolver.resolve(reg, {})
        names = [d.name for d in result.ordered_nodes]
        assert names.index("root") < names.index("left")
        assert names.index("root") < names.index("right")
        assert names.index("left") < names.index("merge")
        assert names.index("right") < names.index("merge")


# ---------------------------------------------------------------------------
# input_type filtering
# ---------------------------------------------------------------------------

class TestInputTypeFiltering:
    def test_text_path(self):
        reg = _build_registry(
            _desc("create", produces=["job"], is_entry=True),
            _desc("text_analyze", requires=["job"], produces=["spec"], input_types=["text"]),
            _desc("draw_analyze", requires=["job"], produces=["spec"], input_types=["drawing"]),
        )
        result = DependencyResolver.resolve(reg, {}, input_type="text")
        names = {d.name for d in result.ordered_nodes}
        assert "text_analyze" in names
        assert "draw_analyze" not in names

    def test_drawing_path(self):
        reg = _build_registry(
            _desc("create", produces=["job"], is_entry=True),
            _desc("text_analyze", requires=["job"], produces=["intent"], input_types=["text"]),
            _desc("draw_analyze", requires=["job"], produces=["spec"], input_types=["drawing"]),
        )
        result = DependencyResolver.resolve(reg, {}, input_type="drawing")
        names = {d.name for d in result.ordered_nodes}
        assert "draw_analyze" in names
        assert "text_analyze" not in names

    def test_no_input_type_includes_all(self):
        reg = _build_registry(
            _desc("text_only", input_types=["text"], produces=["a"]),
            _desc("draw_only", input_types=["drawing"], produces=["b"]),
        )
        result = DependencyResolver.resolve(reg, {}, input_type=None)
        names = {d.name for d in result.ordered_nodes}
        assert names == {"text_only", "draw_only"}


# ---------------------------------------------------------------------------
# OR dependencies
# ---------------------------------------------------------------------------

class TestORDependencies:
    def test_or_dep_one_available(self):
        reg = _build_registry(
            _desc("text_gen", produces=["step_model"], input_types=["text"]),
            _desc("check", requires=[["step_model", "watertight_mesh"]]),
        )
        result = DependencyResolver.resolve(reg, {}, input_type="text")
        names = [d.name for d in result.ordered_nodes]
        assert "text_gen" in names
        assert "check" in names
        assert names.index("text_gen") < names.index("check")

    def test_or_dep_multiple_available(self):
        """When both OR alternatives are available, connect to all producers."""
        reg = _build_registry(
            _desc("gen_step", produces=["step_model"]),
            _desc("gen_mesh", produces=["watertight_mesh"]),
            _desc("check", requires=[["step_model", "watertight_mesh"]]),
        )
        result = DependencyResolver.resolve(reg, {})
        names = [d.name for d in result.ordered_nodes]
        # check should come after both
        assert names.index("gen_step") < names.index("check")
        assert names.index("gen_mesh") < names.index("check")

    def test_or_dep_none_available_raises(self):
        reg = _build_registry(
            _desc("check", requires=[["step_model", "watertight_mesh"]]),
        )
        with pytest.raises(ValueError, match="requires one of"):
            DependencyResolver.resolve(reg, {})


# ---------------------------------------------------------------------------
# is_terminal
# ---------------------------------------------------------------------------

class TestTerminalNode:
    def test_terminal_auto_connected(self):
        reg = _build_registry(
            _desc("gen", produces=["model"]),
            _desc("check", requires=["model"], produces=["report"]),
            _desc("fin", is_terminal=True),
        )
        result = DependencyResolver.resolve(reg, {})
        names = [d.name for d in result.ordered_nodes]
        # finalize should be last
        assert names[-1] == "fin"
        # check → fin edge should exist
        assert ("check", "fin") in result.edges

    def test_terminal_with_no_requires_is_last(self):
        """is_terminal with requires=[] should sort to END, not beginning."""
        reg = _build_registry(
            _desc("a", produces=["x"]),
            _desc("b", requires=["x"]),
            _desc("fin", is_terminal=True),
        )
        result = DependencyResolver.resolve(reg, {})
        names = [d.name for d in result.ordered_nodes]
        assert names[-1] == "fin"

    def test_all_leaves_connect_to_terminal(self):
        """Multiple leaf nodes should all connect to terminal."""
        reg = _build_registry(
            _desc("root", produces=["x"]),
            _desc("leaf1", requires=["x"]),
            _desc("leaf2", requires=["x"]),
            _desc("fin", is_terminal=True),
        )
        result = DependencyResolver.resolve(reg, {})
        terminal_edges = [(s, d) for s, d in result.edges if d == "fin"]
        sources = {s for s, _ in terminal_edges}
        assert "leaf1" in sources
        assert "leaf2" in sources


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

class TestConflictDetection:
    def test_duplicate_producer_raises(self):
        reg = _build_registry(
            _desc("gen1", produces=["model"]),
            _desc("gen2", produces=["model"]),
        )
        with pytest.raises(ValueError, match="Asset conflict"):
            DependencyResolver.resolve(reg, {})

    def test_no_conflict_with_different_input_types(self):
        """Same asset produced by nodes with different input_types — not a conflict
        when filtered by input_type."""
        reg = _build_registry(
            _desc("text_gen", produces=["step_model"], input_types=["text"]),
            _desc("draw_gen", produces=["step_model"], input_types=["drawing"]),
        )
        # Filtered: no conflict
        result = DependencyResolver.resolve(reg, {}, input_type="text")
        assert len(result.ordered_nodes) == 1

    def test_conflict_when_no_input_type_filter(self):
        """Same asset, overlapping input_types, no filter → conflict."""
        reg = _build_registry(
            _desc("a", produces=["x"]),
            _desc("b", produces=["x"]),
        )
        with pytest.raises(ValueError, match="Asset conflict"):
            DependencyResolver.resolve(reg, {}, input_type=None)


# ---------------------------------------------------------------------------
# Missing dependency
# ---------------------------------------------------------------------------

class TestMissingDependency:
    def test_and_dep_missing(self):
        reg = _build_registry(
            _desc("check", requires=["nonexistent"]),
        )
        with pytest.raises(ValueError, match="requires asset 'nonexistent'"):
            DependencyResolver.resolve(reg, {})


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestCycleDetection:
    def test_cycle_raises(self):
        reg = _build_registry(
            _desc("a", requires=["y"], produces=["x"]),
            _desc("b", requires=["x"], produces=["y"]),
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            DependencyResolver.resolve(reg, {})


# ---------------------------------------------------------------------------
# Enabled/disabled filtering
# ---------------------------------------------------------------------------

class TestEnabledFiltering:
    def test_disabled_node_excluded(self):
        reg = _build_registry(
            _desc("a", produces=["x"]),
            _desc("b", requires=["x"]),
        )
        config = {"b": {"enabled": False}}
        result = DependencyResolver.resolve(reg, config)
        names = {d.name for d in result.ordered_nodes}
        assert "a" in names
        assert "b" not in names


# ---------------------------------------------------------------------------
# HITL collection
# ---------------------------------------------------------------------------

class TestHITLCollection:
    def test_hitl_nodes_collected(self):
        reg = _build_registry(
            _desc("a", produces=["x"]),
            _desc("confirm", requires=["x"], supports_hitl=True),
        )
        result = DependencyResolver.resolve(reg, {})
        assert result.interrupt_before == ["confirm"]


# ---------------------------------------------------------------------------
# Full pipeline simulation (text/drawing/organic paths)
# ---------------------------------------------------------------------------

class TestFullPipelinePaths:
    def _build_full_registry(self):
        return _build_registry(
            _desc("create_job", is_entry=True, produces=["job_info"]),
            _desc("analyze_intent", requires=["job_info"], produces=["intent_spec"], input_types=["text"]),
            _desc("analyze_vision", requires=["job_info"], produces=["drawing_spec"], input_types=["drawing"]),
            _desc("analyze_organic", requires=["job_info"], produces=["organic_spec"], input_types=["organic"]),
            _desc("confirm", requires=[["intent_spec", "drawing_spec", "organic_spec"]],
                  produces=["confirmed_params"], supports_hitl=True),
            _desc("gen_text", requires=["confirmed_params"], produces=["step_model"], input_types=["text"]),
            _desc("gen_drawing", requires=["confirmed_params"], produces=["step_model"], input_types=["drawing"]),
            _desc("gen_mesh", requires=["confirmed_params"], produces=["raw_mesh"], input_types=["organic"]),
            _desc("mesh_repair", requires=["raw_mesh"], produces=["watertight_mesh"], input_types=["organic"]),
            _desc("check_print", requires=[["step_model", "watertight_mesh"]], produces=["report"]),
            _desc("finalize", is_terminal=True),
        )

    def test_text_path(self):
        reg = self._build_full_registry()
        result = DependencyResolver.resolve(reg, {}, input_type="text")
        names = [d.name for d in result.ordered_nodes]
        assert "create_job" in names
        assert "analyze_intent" in names
        assert "confirm" in names
        assert "gen_text" in names
        assert "check_print" in names
        assert "finalize" in names
        # Organic nodes excluded
        assert "analyze_organic" not in names
        assert "gen_mesh" not in names
        assert "mesh_repair" not in names

    def test_organic_path(self):
        reg = self._build_full_registry()
        result = DependencyResolver.resolve(reg, {}, input_type="organic")
        names = [d.name for d in result.ordered_nodes]
        assert "create_job" in names
        assert "analyze_organic" in names
        assert "gen_mesh" in names
        assert "mesh_repair" in names
        assert "check_print" in names
        assert "finalize" in names
        # Text/drawing nodes excluded
        assert "analyze_intent" not in names
        assert "gen_text" not in names

    def test_resolve_all_for_compilation(self):
        """resolve_all includes ALL nodes (for single compiled graph)."""
        reg = self._build_full_registry()
        result = DependencyResolver.resolve_all(reg, {})
        names = {d.name for d in result.ordered_nodes}
        assert len(names) == 11  # all nodes
