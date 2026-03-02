"""Tests for NodeDescriptor, NodeResult, and NodeStrategy."""

import pytest

from backend.graph.descriptor import NodeDescriptor, NodeResult, NodeStrategy


class TestNodeDescriptor:
    def test_minimal_construction(self):
        async def my_fn(ctx):
            pass

        desc = NodeDescriptor(name="test_node", display_name="Test", fn=my_fn)
        assert desc.name == "test_node"
        assert desc.display_name == "Test"
        assert desc.fn is my_fn

    def test_defaults(self):
        async def my_fn(ctx):
            pass

        desc = NodeDescriptor(name="n", display_name="N", fn=my_fn)
        assert desc.requires == []
        assert desc.produces == []
        assert desc.input_types == ["text", "drawing", "organic"]
        assert desc.config_model is None
        assert desc.strategies == {}
        assert desc.default_strategy is None
        assert desc.is_entry is False
        assert desc.is_terminal is False
        assert desc.supports_hitl is False
        assert desc.non_fatal is False
        assert desc.description == ""
        assert desc.estimated_duration == ""

    def test_full_construction(self):
        async def my_fn(ctx):
            pass

        class MockStrategy(NodeStrategy):
            async def execute(self, ctx):
                pass

        desc = NodeDescriptor(
            name="analyze",
            display_name="分析",
            fn=my_fn,
            requires=["text_input"],
            produces=["intent_spec"],
            input_types=["text"],
            strategies={"default": MockStrategy},
            default_strategy="default",
            is_entry=False,
            supports_hitl=False,
            non_fatal=False,
            description="Analyze user intent",
            estimated_duration="5s",
        )
        assert desc.requires == ["text_input"]
        assert desc.produces == ["intent_spec"]
        assert desc.input_types == ["text"]
        assert "default" in desc.strategies
        assert desc.default_strategy == "default"
        assert desc.description == "Analyze user intent"

    def test_or_dependency_syntax(self):
        async def my_fn(ctx):
            pass

        desc = NodeDescriptor(
            name="confirm",
            display_name="Confirm",
            fn=my_fn,
            requires=[["intent_spec", "drawing_spec", "organic_spec"]],
        )
        # OR dependency is a list within the requires list
        assert len(desc.requires) == 1
        assert isinstance(desc.requires[0], list)
        assert "intent_spec" in desc.requires[0]

    def test_is_terminal_flag(self):
        async def my_fn(ctx):
            pass

        desc = NodeDescriptor(
            name="finalize",
            display_name="完成",
            fn=my_fn,
            is_terminal=True,
        )
        assert desc.is_terminal is True


class TestNodeResult:
    def test_defaults(self):
        r = NodeResult()
        assert r.assets_produced == []
        assert r.data_produced == []
        assert r.reasoning == {}

    def test_construction(self):
        r = NodeResult(
            assets_produced=["step_model"],
            data_produced=["generated_code"],
            reasoning={"method": "template_first"},
        )
        assert r.assets_produced == ["step_model"]
        assert r.reasoning["method"] == "template_first"


class TestNodeStrategy:
    def test_abc_enforcement(self):
        with pytest.raises(TypeError):
            NodeStrategy()  # type: ignore[abstract]

    def test_concrete_strategy(self):
        class MyStrategy(NodeStrategy):
            async def execute(self, ctx):
                return "done"

        s = MyStrategy()
        assert s.check_available() is True

    def test_unavailable_strategy(self):
        class UnavailableStrategy(NodeStrategy):
            async def execute(self, ctx):
                pass

            def check_available(self) -> bool:
                return False

        s = UnavailableStrategy()
        assert s.check_available() is False


class TestFallbackChain:
    def test_descriptor_default_empty_fallback_chain(self):
        """NodeDescriptor.fallback_chain defaults to empty list."""
        async def noop(ctx): pass
        desc = NodeDescriptor(name="t", display_name="T", fn=noop)
        assert desc.fallback_chain == []

    def test_descriptor_with_fallback_chain(self):
        async def noop(ctx): pass

        class StratA(NodeStrategy):
            async def execute(self, ctx): pass
        class StratB(NodeStrategy):
            async def execute(self, ctx): pass

        desc = NodeDescriptor(
            name="t", display_name="T", fn=noop,
            strategies={"a": StratA, "b": StratB},
            fallback_chain=["a", "b"],
        )
        assert desc.fallback_chain == ["a", "b"]
