"""Tests for AssetRegistry, NodeContext, and PipelineState."""

import pytest

from backend.graph.context import AssetEntry, AssetRegistry, NodeContext
from backend.graph.descriptor import NodeDescriptor, NodeStrategy
from backend.graph.configs.base import BaseNodeConfig
from backend.graph.pipeline_state import PipelineState, _merge_dicts


# ---------------------------------------------------------------------------
# _merge_dicts reducer
# ---------------------------------------------------------------------------

class TestMergeDicts:
    def test_empty_merge(self):
        assert _merge_dicts({}, {}) == {}

    def test_non_overlapping(self):
        assert _merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_overlapping_update_wins(self):
        assert _merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}

    def test_original_not_mutated(self):
        original = {"a": 1}
        _merge_dicts(original, {"b": 2})
        assert original == {"a": 1}


# ---------------------------------------------------------------------------
# AssetEntry
# ---------------------------------------------------------------------------

class TestAssetEntry:
    def test_to_dict(self):
        e = AssetEntry(key="step", path="/tmp/step.stp", format="STEP", producer="gen")
        d = e.to_dict()
        assert d["key"] == "step"
        assert d["format"] == "STEP"
        assert d["metadata"] == {}


# ---------------------------------------------------------------------------
# AssetRegistry
# ---------------------------------------------------------------------------

class TestAssetRegistry:
    def test_put_get(self):
        reg = AssetRegistry()
        reg.put("mesh", "/tmp/mesh.obj", "OBJ", "repair")
        entry = reg.get("mesh")
        assert entry.path == "/tmp/mesh.obj"
        assert entry.producer == "repair"

    def test_get_missing_raises(self):
        reg = AssetRegistry()
        with pytest.raises(KeyError, match="Asset not found: missing"):
            reg.get("missing")

    def test_has(self):
        reg = AssetRegistry()
        assert reg.has("x") is False
        reg.put("x", "/tmp/x", "bin", "test")
        assert reg.has("x") is True

    def test_keys(self):
        reg = AssetRegistry()
        reg.put("a", "/a", "bin", "p")
        reg.put("b", "/b", "bin", "p")
        assert sorted(reg.keys()) == ["a", "b"]

    def test_round_trip(self):
        reg = AssetRegistry()
        reg.put("step", "/tmp/out.stp", "STEP", "gen", {"size_mb": 1.5})
        reg.put("glb", "/tmp/out.glb", "GLB", "preview")

        d = reg.to_dict()
        reg2 = AssetRegistry.from_dict(d)

        assert reg2.has("step")
        assert reg2.has("glb")
        assert reg2.get("step").metadata == {"size_mb": 1.5}
        assert reg2.get("glb").producer == "preview"


# ---------------------------------------------------------------------------
# NodeContext
# ---------------------------------------------------------------------------

def _make_descriptor(**overrides) -> NodeDescriptor:
    async def noop(ctx):
        pass

    defaults = dict(name="test_node", display_name="Test", fn=noop)
    defaults.update(overrides)
    return NodeDescriptor(**defaults)


class TestNodeContextFromState:
    def test_basic_from_state(self):
        state = {
            "job_id": "j1",
            "input_type": "text",
            "assets": {"step": {"key": "step", "path": "/s", "format": "STEP", "producer": "g", "metadata": {}}},
            "data": {"text_input": "make a cube"},
            "pipeline_config": {},
            "node_trace": [],
        }
        desc = _make_descriptor()
        ctx = NodeContext.from_state(state, desc)

        assert ctx.job_id == "j1"
        assert ctx.input_type == "text"
        assert ctx.has_asset("step")
        assert ctx.get_data("text_input") == "make a cube"

    def test_empty_state(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        assert ctx.job_id == ""
        assert ctx.input_type == ""
        assert not ctx.has_asset("anything")

    def test_config_from_pipeline_config(self):
        state = {
            "pipeline_config": {
                "test_node": {"enabled": False, "strategy": "fast"},
            },
        }
        desc = _make_descriptor()
        ctx = NodeContext.from_state(state, desc)
        assert ctx.config.enabled is False
        assert ctx.config.strategy == "fast"

    def test_deep_copy_isolation(self):
        """Verify modifying context data doesn't affect original state."""
        state = {"data": {"items": [1, 2, 3]}}
        ctx = NodeContext.from_state(state, _make_descriptor())
        ctx._data["items"].append(4)
        assert state["data"]["items"] == [1, 2, 3]


class TestNodeContextAssets:
    def test_put_and_get_asset(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        ctx.put_asset("mesh", "/tmp/m.obj", "OBJ", {"vertices": 1000})

        entry = ctx.get_asset("mesh")
        assert entry.path == "/tmp/m.obj"
        assert entry.producer == "test_node"
        assert entry.metadata == {"vertices": 1000}

    def test_new_assets_tracked(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        ctx.put_asset("a", "/a", "bin")
        assert "a" in ctx._new_assets


class TestNodeContextData:
    def test_put_and_get_data(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        ctx.put_data("intent", {"type": "cube"})
        assert ctx.get_data("intent") == {"type": "cube"}

    def test_get_data_default(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        assert ctx.get_data("missing") is None
        assert ctx.get_data("missing", "fallback") == "fallback"

    def test_new_data_tracked(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        ctx.put_data("k", "v")
        assert ctx._new_data == {"k": "v"}


class TestNodeContextStrategy:
    def test_get_strategy(self):
        class FastStrategy(NodeStrategy):
            async def execute(self, ctx):
                return "fast"

        desc = _make_descriptor(strategies={"fast": FastStrategy}, default_strategy="fast")
        state = {"pipeline_config": {"test_node": {"strategy": "fast"}}}
        ctx = NodeContext.from_state(state, desc)

        strategy = ctx.get_strategy()
        assert isinstance(strategy, FastStrategy)

    def test_missing_strategy_raises(self):
        desc = _make_descriptor(strategies={"a": type("A", (NodeStrategy,), {
            "execute": lambda s, c: None,
        })})
        state = {"pipeline_config": {"test_node": {"strategy": "nonexistent"}}}
        ctx = NodeContext.from_state(state, desc)
        with pytest.raises(ValueError, match="not found"):
            ctx.get_strategy()

    def test_no_strategies_raises(self):
        desc = _make_descriptor(strategies={})
        ctx = NodeContext.from_state({}, desc)
        with pytest.raises(ValueError, match="no strategies defined"):
            ctx.get_strategy()

    def test_unavailable_strategy_raises(self):
        class BadStrategy(NodeStrategy):
            async def execute(self, ctx):
                pass
            def check_available(self) -> bool:
                return False

        desc = _make_descriptor(strategies={"bad": BadStrategy})
        state = {"pipeline_config": {"test_node": {"strategy": "bad"}}}
        ctx = NodeContext.from_state(state, desc)
        with pytest.raises(RuntimeError, match="not available"):
            ctx.get_strategy()

    def test_strategy_receives_config(self):
        """get_strategy() passes config to strategy constructor."""

        class ConfigAwareStrategy(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
                self.received_config = config

            async def execute(self, ctx):
                return "ok"

        desc = _make_descriptor(
            strategies={"aware": ConfigAwareStrategy},
        )
        state = {"pipeline_config": {"test_node": {"strategy": "aware"}}}
        ctx = NodeContext.from_state(state, desc)
        strategy = ctx.get_strategy()

        assert isinstance(strategy, ConfigAwareStrategy)
        assert strategy.received_config is ctx.config

    def test_no_arg_strategy_still_works(self):
        """Existing strategies without explicit config param still work
        because NodeStrategy base class has __init__(config=None)."""

        class LegacyStrategy(NodeStrategy):
            async def execute(self, ctx):
                return "legacy"

        desc = _make_descriptor(strategies={"legacy": LegacyStrategy})
        state = {"pipeline_config": {"test_node": {"strategy": "legacy"}}}
        ctx = NodeContext.from_state(state, desc)
        strategy = ctx.get_strategy()
        assert isinstance(strategy, LegacyStrategy)


class TestNodeContextStateDiff:
    def test_empty_diff(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        diff = ctx.to_state_diff()
        assert diff == {}

    def test_incremental_assets_only(self):
        state = {
            "assets": {"old": {"key": "old", "path": "/old", "format": "bin", "producer": "p", "metadata": {}}},
        }
        ctx = NodeContext.from_state(state, _make_descriptor())
        ctx.put_asset("new", "/new", "bin")

        diff = ctx.to_state_diff()
        # Only new asset in diff, not old
        assert "new" in diff["assets"]
        assert "old" not in diff["assets"]

    def test_incremental_data_only(self):
        state = {"data": {"existing": 42}}
        ctx = NodeContext.from_state(state, _make_descriptor())
        ctx.put_data("added", "hello")

        diff = ctx.to_state_diff()
        assert diff["data"] == {"added": "hello"}
        assert "existing" not in diff.get("data", {})

    def test_trace_entries(self):
        ctx = NodeContext.from_state({}, _make_descriptor())
        ctx.add_trace({"node": "test", "elapsed_ms": 100})

        diff = ctx.to_state_diff()
        assert len(diff["node_trace"]) == 1
        assert diff["node_trace"][0]["elapsed_ms"] == 100
