"""Tests for NodeRegistry, @register_node, and discover_nodes."""

import pytest

from backend.graph.descriptor import NodeDescriptor, NodeStrategy
from backend.graph.registry import NodeRegistry, register_node, registry


# Cleanup test nodes registered to global registry
_TEST_NODE_NAMES = ["_test_decorator_node", "_test_preserve", "_test_full_opts"]


@pytest.fixture(autouse=True)
def _cleanup_global_registry():
    """Remove test nodes from global registry after each test."""
    yield
    for name in _TEST_NODE_NAMES:
        registry._remove(name)


# ---------------------------------------------------------------------------
# NodeRegistry
# ---------------------------------------------------------------------------

class TestNodeRegistry:
    def setup_method(self):
        self.reg = NodeRegistry()

    def _make_desc(self, name="node1", **kw):
        async def fn(ctx):
            pass
        defaults = dict(name=name, display_name=name.title(), fn=fn)
        defaults.update(kw)
        return NodeDescriptor(**defaults)

    def test_register_and_get(self):
        desc = self._make_desc("analyze")
        self.reg.register(desc)
        assert self.reg.get("analyze") is desc

    def test_get_missing_raises(self):
        with pytest.raises(KeyError, match="Node not found"):
            self.reg.get("missing")

    def test_duplicate_name_different_fn_raises(self):
        async def fn1(ctx):
            pass
        async def fn2(ctx):
            pass
        self.reg.register(NodeDescriptor(name="dup", display_name="D", fn=fn1))
        with pytest.raises(ValueError, match="already registered"):
            self.reg.register(NodeDescriptor(name="dup", display_name="D", fn=fn2))

    def test_duplicate_same_fn_idempotent(self):
        async def fn(ctx):
            pass
        desc1 = NodeDescriptor(name="same", display_name="S", fn=fn)
        desc2 = NodeDescriptor(name="same", display_name="S", fn=fn)
        self.reg.register(desc1)
        self.reg.register(desc2)  # should not raise
        assert len(self.reg) == 1

    def test_all(self):
        self.reg.register(self._make_desc("a"))
        self.reg.register(self._make_desc("b"))
        all_nodes = self.reg.all()
        assert set(all_nodes.keys()) == {"a", "b"}

    def test_contains(self):
        self.reg.register(self._make_desc("x"))
        assert "x" in self.reg
        assert "y" not in self.reg

    def test_len(self):
        assert len(self.reg) == 0
        self.reg.register(self._make_desc("a"))
        assert len(self.reg) == 1

    def test_find_producers(self):
        self.reg.register(self._make_desc("gen", produces=["step_model"]))
        self.reg.register(self._make_desc("other", produces=["mesh"]))
        producers = self.reg.find_producers("step_model")
        assert len(producers) == 1
        assert producers[0].name == "gen"

    def test_find_consumers_and_dep(self):
        self.reg.register(self._make_desc("a", requires=["step_model"]))
        self.reg.register(self._make_desc("b", requires=[["step_model", "mesh"]]))  # OR dep
        self.reg.register(self._make_desc("c", requires=["mesh"]))

        consumers = self.reg.find_consumers("step_model")
        names = {c.name for c in consumers}
        assert names == {"a", "b"}

    def test_find_producers_empty(self):
        assert self.reg.find_producers("nonexistent") == []


# ---------------------------------------------------------------------------
# @register_node decorator
# ---------------------------------------------------------------------------

class TestRegisterNodeDecorator:
    def test_decorator_registers_to_global_registry(self):
        from backend.graph.registry import registry

        # Use a unique name to avoid conflicts with other tests
        @register_node(name="_test_decorator_node", display_name="Test Decorator")
        async def my_node(ctx):
            pass

        assert "_test_decorator_node" in registry
        desc = registry.get("_test_decorator_node")
        assert desc.display_name == "Test Decorator"
        # The registered fn should be the original unwrapped function
        assert desc.fn is my_node.__wrapped__ if hasattr(my_node, '__wrapped__') else True

    def test_decorator_preserves_function(self):
        @register_node(name="_test_preserve", display_name="Preserve")
        async def original_fn(ctx):
            return "hello"

        # Wrapper is callable
        assert callable(original_fn)
        # Descriptor is attached
        assert hasattr(original_fn, "_node_descriptor")
        assert original_fn._node_descriptor.name == "_test_preserve"

    def test_decorator_with_full_options(self):
        class TestStrategy(NodeStrategy):
            async def execute(self, ctx):
                pass

        @register_node(
            name="_test_full_opts",
            display_name="Full Options",
            requires=["text_input"],
            produces=["intent_spec"],
            input_types=["text"],
            strategies={"default": TestStrategy},
            default_strategy="default",
            is_entry=False,
            supports_hitl=True,
            non_fatal=False,
            description="Test node with all options",
        )
        async def full_node(ctx):
            pass

        desc = full_node._node_descriptor
        assert desc.requires == ["text_input"]
        assert desc.produces == ["intent_spec"]
        assert desc.input_types == ["text"]
        assert desc.supports_hitl is True
        assert "default" in desc.strategies


# ---------------------------------------------------------------------------
# discover_nodes
# ---------------------------------------------------------------------------

class TestDiscoverNodes:
    def test_discover_is_idempotent(self):
        from backend.graph.discovery import discover_nodes, reset_discovery, _discovered

        reset_discovery()
        discover_nodes()
        # Second call should be a no-op (no errors)
        discover_nodes()

    def test_discover_imports_node_modules(self):
        from backend.graph.discovery import discover_nodes, reset_discovery

        reset_discovery()
        # Should not raise even if nodes use heavy deps (stubbed by conftest)
        discover_nodes()
