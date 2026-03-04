"""Tests for runtime node skip and resolver include_disabled."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_dispatch():
    """Mock _safe_dispatch to capture SSE events."""
    with patch("backend.graph.builder._safe_dispatch", new_callable=AsyncMock) as m:
        yield m


class TestWrapNodeSkip:
    """_wrap_node() runtime skip behavior."""

    def _make_desc(self, name="test_node", fn=None):
        from backend.graph.descriptor import NodeDescriptor

        return NodeDescriptor(
            name=name,
            display_name="Test",
            fn=fn or AsyncMock(return_value={"out": "val"}),
            requires=[],
            produces=["test_asset"],
            input_types=["text"],
            config_model=None,
            strategies={},
            default_strategy=None,
            fallback_chain=[],
            is_entry=False,
            is_terminal=False,
            supports_hitl=False,
            non_fatal=False,
            description="",
            estimated_duration="",
        )

    def _make_builder(self):
        from backend.graph.builder import PipelineBuilder

        return PipelineBuilder()

    async def test_skip_emits_events_and_returns_skip_trace(self, mock_dispatch):
        """Disabled node: emit node.skipped, return skip trace, don't execute fn."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {
            "job_id": "j1",
            "pipeline_config": {"test_node": {"enabled": False}},
        }

        result = await wrapped(state)

        # Returns skip trace entry (not empty dict)
        assert result == {"node_trace": [{
            "node": "test_node",
            "skipped": True,
            "elapsed_ms": 0,
            "assets_produced": [],
        }]}
        desc.fn.assert_not_called()

        # Only node.skipped event (no node.started for disabled nodes)
        events = [call.args[0] for call in mock_dispatch.call_args_list]
        assert "node.skipped" in events
        assert "node.started" not in events

    async def test_skip_event_payload(self, mock_dispatch):
        """node.skipped event includes job_id, node, reason."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {
            "job_id": "j42",
            "pipeline_config": {"test_node": {"enabled": False}},
        }

        await wrapped(state)

        # Find the node.skipped call
        skipped_call = None
        for call in mock_dispatch.call_args_list:
            if call.args[0] == "node.skipped":
                skipped_call = call
                break

        assert skipped_call is not None
        payload = skipped_call.args[1]
        assert payload["job_id"] == "j42"
        assert payload["node"] == "test_node"
        assert payload["reason"] == "disabled"

    @patch("backend.graph.context.NodeContext.from_state")
    async def test_enabled_node_executes_normally(self, mock_ctx_from_state, mock_dispatch):
        """Enabled node executes fn and returns diff."""
        mock_ctx = MagicMock()
        mock_ctx._fallback_trace = None
        mock_ctx.to_state_diff.return_value = {"data": {"key": "val"}}
        mock_ctx_from_state.return_value = mock_ctx

        fn = AsyncMock(return_value={"out": "val"})
        desc = self._make_desc(fn=fn)
        wrapped = self._make_builder()._wrap_node(desc)

        state = {
            "job_id": "j1",
            "pipeline_config": {"test_node": {"enabled": True}},
        }

        result = await wrapped(state)

        assert result != {}
        fn.assert_called_once()

        # Should emit node.started + node.completed (not node.skipped)
        events = [call.args[0] for call in mock_dispatch.call_args_list]
        assert "node.started" in events
        assert "node.completed" in events
        assert "node.skipped" not in events

    @patch("backend.graph.context.NodeContext.from_state")
    async def test_default_enabled_when_not_in_config(self, mock_ctx_from_state, mock_dispatch):
        """Node not in pipeline_config defaults to enabled."""
        mock_ctx = MagicMock()
        mock_ctx._fallback_trace = None
        mock_ctx.to_state_diff.return_value = {}
        mock_ctx_from_state.return_value = mock_ctx

        fn = AsyncMock(return_value={"out": "val"})
        desc = self._make_desc(fn=fn)
        wrapped = self._make_builder()._wrap_node(desc)

        state = {"job_id": "j1", "pipeline_config": {}}

        result = await wrapped(state)

        fn.assert_called_once()
        events = [call.args[0] for call in mock_dispatch.call_args_list]
        assert "node.skipped" not in events

    async def test_no_pipeline_config_defaults_enabled(self, mock_dispatch):
        """Missing pipeline_config key entirely defaults to enabled."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {"job_id": "j1"}

        with patch("backend.graph.context.NodeContext.from_state") as mock_ctx:
            ctx = MagicMock()
            ctx._fallback_trace = None
            ctx.to_state_diff.return_value = {}
            mock_ctx.return_value = ctx
            desc.fn.return_value = {"out": "val"}

            result = await wrapped(state)

        desc.fn.assert_called_once()
        events = [call.args[0] for call in mock_dispatch.call_args_list]
        assert "node.skipped" not in events


class TestResolverIncludeDisabled:
    """DependencyResolver.resolve() include_disabled parameter."""

    def _make_registry_with_nodes(self):
        """Create a minimal registry with a few test nodes."""
        from backend.graph.descriptor import NodeDescriptor
        from backend.graph.registry import NodeRegistry

        reg = NodeRegistry()

        # Entry node
        entry_fn = AsyncMock()
        entry = NodeDescriptor(
            name="entry_node",
            display_name="Entry",
            fn=entry_fn,
            requires=[],
            produces=["entry_asset"],
            input_types=["text"],
            is_entry=True,
        )
        reg.register(entry)

        # Middle node (toggleable)
        mid_fn = AsyncMock()
        mid = NodeDescriptor(
            name="middle_node",
            display_name="Middle",
            fn=mid_fn,
            requires=["entry_asset"],
            produces=["mid_asset"],
            input_types=["text"],
        )
        reg.register(mid)

        # Terminal node
        term_fn = AsyncMock()
        term = NodeDescriptor(
            name="terminal_node",
            display_name="Terminal",
            fn=term_fn,
            requires=["mid_asset"],
            produces=[],
            input_types=["text"],
            is_terminal=True,
        )
        reg.register(term)

        return reg

    def test_include_disabled_true_keeps_all(self):
        """include_disabled=True keeps disabled nodes in resolved pipeline."""
        from backend.graph.resolver import DependencyResolver

        reg = self._make_registry_with_nodes()
        config = {"middle_node": {"enabled": False}}

        resolved = DependencyResolver.resolve(
            reg, config, "text", include_disabled=True,
        )
        names = {d.name for d in resolved.ordered_nodes}
        assert "middle_node" in names

    def test_include_disabled_false_filters(self):
        """include_disabled=False excludes disabled nodes."""
        from backend.graph.resolver import DependencyResolver

        reg = self._make_registry_with_nodes()

        # Build a simpler registry where filtering won't break deps
        from backend.graph.descriptor import NodeDescriptor
        from backend.graph.registry import NodeRegistry

        reg2 = NodeRegistry()
        entry = NodeDescriptor(
            name="entry_node", display_name="Entry",
            fn=AsyncMock(), requires=[], produces=["a"],
            input_types=["text"], is_entry=True,
        )
        reg2.register(entry)

        optional = NodeDescriptor(
            name="optional_node", display_name="Optional",
            fn=AsyncMock(), requires=["a"], produces=["b"],
            input_types=["text"], non_fatal=True,
        )
        reg2.register(optional)

        term = NodeDescriptor(
            name="terminal_node", display_name="Terminal",
            fn=AsyncMock(), requires=["a"], produces=[],
            input_types=["text"], is_terminal=True,
        )
        reg2.register(term)

        config = {"optional_node": {"enabled": False}}
        resolved = DependencyResolver.resolve(
            reg2, config, "text", include_disabled=False,
        )
        names = {d.name for d in resolved.ordered_nodes}
        assert "optional_node" not in names
        assert "entry_node" in names
        assert "terminal_node" in names

    def test_default_include_disabled_is_true(self):
        """Default include_disabled=True (backward compat)."""
        from backend.graph.resolver import DependencyResolver

        reg = self._make_registry_with_nodes()
        config = {"middle_node": {"enabled": False}}

        # Call without include_disabled — should default to True
        resolved = DependencyResolver.resolve(reg, config, "text")
        names = {d.name for d in resolved.ordered_nodes}
        assert "middle_node" in names
