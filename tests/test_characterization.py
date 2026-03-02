"""Characterization tests — lock down current behavior before refactoring.

These tests capture the exact contracts (SSE events, HITL resume format,
DB persistence, API response shape) that the new plugin pipeline must
preserve.  They serve as a regression safety net during migration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.graph.state import CadJobState, STATE_TO_ORM_MAPPING


# ---------------------------------------------------------------------------
# SSE Event Contract
# ---------------------------------------------------------------------------


class TestSSEEventContract:
    """Verify @timed_node dispatches events with expected payloads."""

    @pytest.mark.asyncio
    async def test_timed_node_dispatches_started_and_completed(self):
        """node.started and node.completed events must contain job_id, node, timestamp."""
        from backend.graph.decorators import timed_node

        dispatched_events: list[tuple[str, dict]] = []

        async def mock_dispatch(event_name, payload):
            dispatched_events.append((event_name, payload))

        @timed_node("test_node")
        async def sample_node(state):
            return {"output_key": "value", "_reasoning": {"method": "test"}}

        state = {"job_id": "evt-1"}

        with patch("backend.graph.decorators._safe_dispatch", side_effect=mock_dispatch):
            result = await sample_node(state)

        # Two events dispatched
        assert len(dispatched_events) == 2
        started = dispatched_events[0]
        completed = dispatched_events[1]

        # node.started
        assert started[0] == "node.started"
        assert started[1]["job_id"] == "evt-1"
        assert started[1]["node"] == "test_node"
        assert "timestamp" in started[1]

        # node.completed
        assert completed[0] == "node.completed"
        assert completed[1]["job_id"] == "evt-1"
        assert completed[1]["node"] == "test_node"
        assert "elapsed_ms" in completed[1]
        assert completed[1]["reasoning"] == {"method": "test"}
        assert "outputs_summary" in completed[1]

        # _reasoning stripped from result
        assert "_reasoning" not in result

    @pytest.mark.asyncio
    async def test_timed_node_dispatches_failed_on_exception(self):
        from backend.graph.decorators import timed_node

        dispatched_events: list[tuple[str, dict]] = []

        async def mock_dispatch(event_name, payload):
            dispatched_events.append((event_name, payload))

        @timed_node("fail_node")
        async def failing_node(state):
            raise RuntimeError("boom")

        state = {"job_id": "evt-2"}

        with patch("backend.graph.decorators._safe_dispatch", side_effect=mock_dispatch):
            with pytest.raises(RuntimeError, match="boom"):
                await failing_node(state)

        assert len(dispatched_events) == 2
        started = dispatched_events[0]
        failed = dispatched_events[1]

        assert started[0] == "node.started"
        assert failed[0] == "node.failed"
        assert failed[1]["error"] == "boom"
        assert "elapsed_ms" in failed[1]


# ---------------------------------------------------------------------------
# HITL Resume Contract
# ---------------------------------------------------------------------------


class TestHITLResumeContract:
    """Verify confirm endpoint resume data format.

    The current contract: confirmed_params, confirmed_spec, disclaimer_accepted
    are injected as top-level CadJobState fields via Command(resume=...).
    """

    def test_confirm_request_schema(self):
        """ConfirmRequest fields must match what LangGraph resume expects."""
        from backend.api.v1.jobs import ConfirmRequest

        req = ConfirmRequest(
            confirmed_params={"diameter": 50, "teeth": 20},
            confirmed_spec={"part_type": "rotational"},
            base_body_method="revolve",
            disclaimer_accepted=True,
        )
        assert req.confirmed_params == {"diameter": 50, "teeth": 20}
        assert req.confirmed_spec == {"part_type": "rotational"}
        assert req.disclaimer_accepted is True

    def test_confirm_with_user_node_outputs_status_confirmed(self):
        """confirm_with_user_node must return status=confirmed."""
        # This is already tested in test_graph_nodes_lifecycle.py
        # but we re-assert here as a characterization test
        from backend.graph.nodes.lifecycle import confirm_with_user_node
        import asyncio

        state = CadJobState(
            job_id="hitl-1",
            input_type="text",
            status="awaiting_confirmation",
            confirmed_params={"d": 10},
            disclaimer_accepted=True,
        )
        result = asyncio.get_event_loop().run_until_complete(confirm_with_user_node(state))
        assert result["status"] == "confirmed"


# ---------------------------------------------------------------------------
# Finalize DB Persistence Contract
# ---------------------------------------------------------------------------


class TestFinalizePersistenceContract:
    """Lock down finalize_node's DB write format."""

    def test_state_to_orm_mapping_fields(self):
        """STATE_TO_ORM_MAPPING must map these specific fields."""
        assert STATE_TO_ORM_MAPPING["confirmed_spec"] == "drawing_spec_confirmed"
        assert STATE_TO_ORM_MAPPING["printability"] == "printability_result"

    @pytest.mark.asyncio
    async def test_finalize_assembles_result_json(self):
        """finalize_node must assemble step_path + model_url into result JSON."""
        from backend.graph.nodes.lifecycle import finalize_node

        state = CadJobState(
            job_id="db-1",
            input_type="text",
            status="generating",
            step_path="/outputs/db-1/model.step",
            model_url="/outputs/db-1/model.glb",
            printability={"score": 0.95},
            error=None,
        )
        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock) as mock:
            await finalize_node(state)

        kw = mock.call_args[1]
        assert kw["status"] == "completed"
        assert kw["result"]["step_path"] == "/outputs/db-1/model.step"
        assert kw["result"]["model_url"] == "/outputs/db-1/model.glb"
        assert kw["printability_result"] == {"score": 0.95}

    @pytest.mark.asyncio
    async def test_finalize_organic_assembles_mesh_result(self):
        """finalize_node for organic must merge organic_result into result JSON."""
        from backend.graph.nodes.lifecycle import finalize_node

        organic_result = {
            "model_url": "/out/model.glb",
            "stl_url": "/out/model.stl",
            "threemf_url": "/out/model.3mf",
            "mesh_stats": {"vertex_count": 500, "is_watertight": True},
            "warnings": [],
            "printability": {"printable": True},
        }
        state = CadJobState(
            job_id="org-db",
            input_type="organic",
            status="post_processed",
            organic_result=organic_result,
            error=None,
        )
        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock) as mock:
            await finalize_node(state)

        kw = mock.call_args[1]
        assert kw["status"] == "completed"
        assert kw["result"]["model_url"] == "/out/model.glb"
        assert kw["result"]["stl_url"] == "/out/model.stl"
        assert kw["result"]["threemf_url"] == "/out/model.3mf"

    @pytest.mark.asyncio
    async def test_finalize_dispatches_terminal_event(self):
        """finalize_node must dispatch job.completed or job.failed."""
        from backend.graph.nodes.lifecycle import finalize_node

        dispatched: list[tuple[str, dict]] = []

        async def capture(event_name, payload):
            dispatched.append((event_name, payload))

        state = CadJobState(
            job_id="evt-db",
            input_type="text",
            status="generating",
            step_path="/out/m.step",
            error=None,
        )
        with (
            patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock),
            patch("backend.graph.nodes.lifecycle._safe_dispatch", side_effect=capture),
        ):
            await finalize_node(state)

        assert len(dispatched) == 1
        assert dispatched[0][0] == "job.completed"
        assert dispatched[0][1]["job_id"] == "evt-db"
        assert dispatched[0][1]["status"] == "completed"


# ---------------------------------------------------------------------------
# API Response Schema Contract
# ---------------------------------------------------------------------------


class TestAPIResponseSchemaContract:
    """Lock down JobDetailResponse field set."""

    def test_job_detail_response_required_fields(self):
        from backend.api.v1.jobs import JobDetailResponse

        # These fields MUST exist in the response model
        required = {
            "job_id", "status", "input_type", "input_text",
            "result", "error", "created_at",
            "printability", "intent", "precise_spec",
            "drawing_spec", "drawing_spec_confirmed",
            "image_path", "organic_spec", "generated_code",
            "parent_job_id", "child_job_ids", "recommendations",
            "corrections",
        }
        actual = set(JobDetailResponse.model_fields.keys())
        missing = required - actual
        assert not missing, f"Missing fields in JobDetailResponse: {missing}"

    def test_confirm_request_fields(self):
        from backend.api.v1.jobs import ConfirmRequest

        required = {"confirmed_params", "confirmed_spec", "base_body_method", "disclaimer_accepted"}
        actual = set(ConfirmRequest.model_fields.keys())
        missing = required - actual
        assert not missing, f"Missing fields in ConfirmRequest: {missing}"
