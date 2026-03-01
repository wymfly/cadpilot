"""Tests for @timed_node decorator."""

import pytest
from unittest.mock import patch, AsyncMock


class TestSummarizeOutputs:
    def test_filters_underscore_keys(self):
        from backend.graph.decorators import _summarize_outputs

        result = _summarize_outputs({"intent": {"x": 1}, "_reasoning": {"y": 2}})
        assert "_reasoning" not in result
        assert "intent" in result

    def test_truncates_long_strings(self):
        from backend.graph.decorators import _summarize_outputs

        result = _summarize_outputs({"code": "x" * 500})
        assert len(result["code"]) <= 210  # 200 + "..."

    def test_empty_dict(self):
        from backend.graph.decorators import _summarize_outputs

        assert _summarize_outputs({}) == {}

    def test_large_dict_summarized(self):
        from backend.graph.decorators import _summarize_outputs

        big = {"k" + str(i): i for i in range(100)}
        result = _summarize_outputs({"data": big})
        assert "data" in result

    def test_preserves_small_values(self):
        from backend.graph.decorators import _summarize_outputs

        result = _summarize_outputs({"status": "ok", "count": 42})
        assert result["status"] == "ok"
        assert result["count"] == 42


class TestTimedNode:
    @pytest.mark.asyncio
    async def test_dispatches_started_and_completed(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            return {"output": "value"}

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            result = await my_node({"job_id": "j1"})

        assert len(dispatched) == 2
        assert dispatched[0][0] == "node.started"
        assert dispatched[0][1]["node"] == "test_node"
        assert dispatched[0][1]["job_id"] == "j1"
        assert dispatched[1][0] == "node.completed"
        assert dispatched[1][1]["elapsed_ms"] >= 0
        assert result == {"output": "value"}

    @pytest.mark.asyncio
    async def test_extracts_reasoning_from_result(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            return {"output": "v", "_reasoning": {"why": "because"}}

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            result = await my_node({"job_id": "j1"})

        # _reasoning removed from result (not written to state)
        assert "_reasoning" not in result
        assert result == {"output": "v"}
        # reasoning attached to node.completed event
        completed = dispatched[1][1]
        assert completed["reasoning"] == {"why": "because"}

    @pytest.mark.asyncio
    async def test_dispatches_failed_on_exception(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            raise ValueError("boom")

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            with pytest.raises(ValueError, match="boom"):
                await my_node({"job_id": "j1"})

        assert dispatched[1][0] == "node.failed"
        assert "boom" in dispatched[1][1]["error"]
        assert dispatched[1][1]["elapsed_ms"] >= 0

    @pytest.mark.asyncio
    async def test_outputs_summary_in_completed(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            return {"step_path": "/tmp/model.step", "status": "ok"}

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            await my_node({"job_id": "j1"})

        summary = dispatched[1][1]["outputs_summary"]
        assert summary["step_path"] == "/tmp/model.step"
        assert summary["status"] == "ok"

    @pytest.mark.asyncio
    async def test_no_reasoning_means_none(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            return {"status": "ok"}

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            await my_node({"job_id": "j1"})

        assert dispatched[1][1]["reasoning"] is None

    @pytest.mark.asyncio
    async def test_missing_job_id_uses_unknown(self):
        from backend.graph.decorators import timed_node

        @timed_node("test_node")
        async def my_node(state):
            return {}

        dispatched = []
        with patch(
            "backend.graph.decorators._safe_dispatch",
            new_callable=AsyncMock,
            side_effect=lambda name, data: dispatched.append((name, data)),
        ):
            await my_node({})

        assert dispatched[0][1]["job_id"] == "unknown"
