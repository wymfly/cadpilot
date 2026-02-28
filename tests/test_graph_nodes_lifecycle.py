"""Tests for lifecycle graph nodes: create, confirm, finalize."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.graph.state import CadJobState


class TestCreateJobNode:
    @pytest.fixture
    def initial_state(self) -> CadJobState:
        return CadJobState(
            job_id="test-123",
            input_type="text",
            input_text="make a gear",
            image_path=None,
            status="pending",
        )

    @pytest.mark.asyncio
    async def test_creates_db_record_and_sets_status(self, initial_state) -> None:
        from backend.graph.nodes.lifecycle import create_job_node

        with patch("backend.graph.nodes.lifecycle.create_job", new_callable=AsyncMock) as mock_create:
            result = await create_job_node(initial_state)

        mock_create.assert_called_once_with(
            job_id="test-123",
            input_type="text",
            input_text="make a gear",
        )
        assert result["status"] == "created"


class TestConfirmWithUserNode:
    @pytest.mark.asyncio
    async def test_sets_confirmed_status(self) -> None:
        from backend.graph.nodes.lifecycle import confirm_with_user_node

        state = CadJobState(
            job_id="test-123",
            input_type="text",
            status="awaiting_confirmation",
            confirmed_params={"diameter": 50, "teeth": 20},
            disclaimer_accepted=True,
        )
        result = await confirm_with_user_node(state)
        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_works_for_drawing_mode(self) -> None:
        from backend.graph.nodes.lifecycle import confirm_with_user_node

        state = CadJobState(
            job_id="test-123",
            input_type="drawing",
            status="awaiting_drawing_confirmation",
            confirmed_spec={"part_type": "rotational", "diameter": 30},
            disclaimer_accepted=True,
        )
        result = await confirm_with_user_node(state)
        assert result["status"] == "confirmed"


class TestFinalizeNode:
    @pytest.mark.asyncio
    async def test_completed_path(self) -> None:
        from backend.graph.nodes.lifecycle import finalize_node

        state = CadJobState(
            job_id="test-123",
            input_type="text",
            status="generating",
            step_path="/outputs/test-123/model.step",
            model_url="/outputs/test-123/model.glb",
            printability={"score": 0.95},
            error=None,
        )
        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock):
            result = await finalize_node(state)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_failed_path(self) -> None:
        from backend.graph.nodes.lifecycle import finalize_node

        state = CadJobState(
            job_id="test-123",
            input_type="text",
            status="failed",
            error="timeout",
            failure_reason="timeout",
        )
        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock):
            result = await finalize_node(state)

        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_orm_mapping_used_correctly(self) -> None:
        from backend.graph.nodes.lifecycle import finalize_node

        state = CadJobState(
            job_id="test-123",
            input_type="text",
            status="generating",
            step_path="/outputs/test-123/model.step",
            printability={"score": 0.95},
            confirmed_spec={"part_type": "rotational"},
            error=None,
        )
        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock) as mock_update:
            await finalize_node(state)

        call_kwargs = mock_update.call_args[1]
        # Verify ORM mapping: printability → printability_result
        assert "printability_result" in call_kwargs
        assert call_kwargs["printability_result"] == {"score": 0.95}
        # Verify ORM mapping: confirmed_spec → drawing_spec_confirmed
        assert "drawing_spec_confirmed" in call_kwargs
        # Verify ORM mapping: step_path → output_step_path
        assert "output_step_path" in call_kwargs
