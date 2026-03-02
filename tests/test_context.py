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


# ---------------------------------------------------------------------------
# get_strategy() auto mode
# ---------------------------------------------------------------------------

class TestGetStrategyAutoMode:
    """Tests for get_strategy() auto mode — selection layer only."""

    def _make_strategies(self):
        class AlgoStrategy(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return "algo"

        class NeuralStrategy(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return "neural"
            def check_available(self):
                return False  # unavailable by default

        return {"algorithm": AlgoStrategy, "neural": NeuralStrategy}

    def test_auto_selects_first_available(self):
        strategies = self._make_strategies()
        desc = _make_descriptor(
            strategies=strategies,
            fallback_chain=["algorithm", "neural"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        strategy = ctx.get_strategy()
        assert type(strategy).__name__ == "AlgoStrategy"

    def test_auto_skips_unavailable(self):
        class UnavailableAlgo(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return "algo"
            def check_available(self):
                return False

        class AvailableNeural(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return "neural"

        desc = _make_descriptor(
            strategies={"algorithm": UnavailableAlgo, "neural": AvailableNeural},
            fallback_chain=["algorithm", "neural"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        strategy = ctx.get_strategy()
        assert type(strategy).__name__ == "AvailableNeural"

    def test_auto_all_unavailable_raises(self):
        class BadStrat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                pass
            def check_available(self):
                return False

        desc = _make_descriptor(
            strategies={"a": BadStrat, "b": BadStrat},
            fallback_chain=["a", "b"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        with pytest.raises(RuntimeError, match="unavailable"):
            ctx.get_strategy()

    def test_auto_no_fallback_chain_raises(self):
        class Strat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                pass

        desc = _make_descriptor(
            strategies={"a": Strat},
            fallback_chain=[],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        with pytest.raises(ValueError, match="no fallback chain"):
            ctx.get_strategy()

    def test_explicit_strategy_unchanged(self):
        """Non-auto mode should work exactly as before."""
        strategies = self._make_strategies()
        desc = _make_descriptor(
            strategies=strategies,
            fallback_chain=["algorithm", "neural"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "algorithm"}}}
        ctx = NodeContext.from_state(state, desc)

        strategy = ctx.get_strategy()
        assert type(strategy).__name__ == "AlgoStrategy"


# ---------------------------------------------------------------------------
# execute_with_fallback() — execution layer
# ---------------------------------------------------------------------------

class TestExecuteWithFallback:
    """Tests for execute_with_fallback() — execution layer."""

    @pytest.mark.asyncio
    async def test_auto_first_succeeds_no_fallback(self):
        class AlgoStrat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return {"result": "algo"}

        desc = _make_descriptor(
            strategies={"algorithm": AlgoStrat},
            fallback_chain=["algorithm"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        result = await ctx.execute_with_fallback()
        assert result == {"result": "algo"}
        assert ctx._fallback_trace["fallback_triggered"] is False
        assert ctx._fallback_trace["strategy_used"] == "algorithm"

    @pytest.mark.asyncio
    async def test_auto_fallback_on_execute_failure(self):
        class FailAlgo(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                raise RuntimeError("algo failed")

        class OkNeural(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return {"result": "neural"}

        desc = _make_descriptor(
            strategies={"algorithm": FailAlgo, "neural": OkNeural},
            fallback_chain=["algorithm", "neural"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        result = await ctx.execute_with_fallback()
        assert result == {"result": "neural"}
        assert ctx._fallback_trace["fallback_triggered"] is True
        attempts = ctx._fallback_trace["strategies_attempted"]
        assert attempts[0]["name"] == "algorithm"
        assert "algo failed" in attempts[0]["error"]
        assert attempts[1]["name"] == "neural"
        assert attempts[1]["result"] == "success"

    @pytest.mark.asyncio
    async def test_auto_all_fail_raises(self):
        class FailStrat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                raise RuntimeError("fail")

        class UnavailStrat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                pass
            def check_available(self):
                return False

        desc = _make_descriptor(
            strategies={"a": FailStrat, "b": UnavailStrat},
            fallback_chain=["a", "b"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        with pytest.raises(RuntimeError, match="No strategy succeeded"):
            await ctx.execute_with_fallback()

        attempts = ctx._fallback_trace["strategies_attempted"]
        assert len(attempts) == 2
        assert "fail" in attempts[0]["error"]
        assert "unavailable" in attempts[1]["error"]

    @pytest.mark.asyncio
    async def test_non_auto_delegates_directly(self):
        class DirectStrat(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return {"result": "direct"}

        desc = _make_descriptor(strategies={"direct": DirectStrat})
        state = {"pipeline_config": {"test_node": {"strategy": "direct"}}}
        ctx = NodeContext.from_state(state, desc)

        result = await ctx.execute_with_fallback()
        assert result == {"result": "direct"}

    @pytest.mark.asyncio
    async def test_auto_skips_unavailable_then_succeeds(self):
        class UnavailAlgo(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return {"result": "algo"}
            def check_available(self):
                return False

        class OkNeural(NodeStrategy):
            def __init__(self, config=None):
                super().__init__(config)
            async def execute(self, ctx):
                return {"result": "neural"}

        desc = _make_descriptor(
            strategies={"algorithm": UnavailAlgo, "neural": OkNeural},
            fallback_chain=["algorithm", "neural"],
        )
        state = {"pipeline_config": {"test_node": {"strategy": "auto"}}}
        ctx = NodeContext.from_state(state, desc)

        result = await ctx.execute_with_fallback()
        assert result == {"result": "neural"}
        assert ctx._fallback_trace["fallback_triggered"] is True
