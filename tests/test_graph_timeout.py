"""Tests for LLM timeout behavior in graph nodes.

These tests verify that analysis nodes return ``{status: "failed",
failure_reason: "timeout"}`` when the underlying LLM call times out,
rather than hanging or propagating the exception.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.graph.state import CadJobState


# ---------------------------------------------------------------------------
# Intent analysis timeout
# ---------------------------------------------------------------------------

class TestIntentTimeoutBehavior:
    """Verify analyze_intent_node handles TimeoutError correctly."""

    @pytest.mark.asyncio
    async def test_timeout_returns_failed_with_reason(self) -> None:
        """TimeoutError should map to status='failed', failure_reason='timeout'."""
        from backend.graph.nodes.analysis import analyze_intent_node

        state = CadJobState(
            job_id="timeout-1",
            input_type="text",
            input_text="make a gear",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError(),
        ):
            result = await analyze_intent_node(state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_timeout_does_not_hang(self) -> None:
        """Node should return promptly when LLM times out (no actual 60s wait)."""
        from backend.graph.nodes.analysis import analyze_intent_node

        state = CadJobState(
            job_id="timeout-2",
            input_type="text",
            input_text="x",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError(),
        ):
            # Should complete in < 5s (mocked TimeoutError is instant)
            result = await asyncio.wait_for(
                analyze_intent_node(state),
                timeout=5.0,
            )

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_timeout_error_message_is_descriptive(self) -> None:
        """The error field should contain a string representation of the exception."""
        from backend.graph.nodes.analysis import analyze_intent_node

        state = CadJobState(
            job_id="timeout-3",
            input_type="text",
            input_text="make a bracket",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=asyncio.TimeoutError(),
        ):
            result = await analyze_intent_node(state)

        # error should be a non-empty string
        assert isinstance(result["error"], str)


# ---------------------------------------------------------------------------
# Vision analysis timeout
# ---------------------------------------------------------------------------

class TestVisionTimeoutBehavior:
    """Verify analyze_vision_node handles TimeoutError correctly."""

    @pytest.mark.asyncio
    async def test_timeout_returns_failed_with_reason(self) -> None:
        """TimeoutError should map to status='failed', failure_reason='timeout'."""
        from backend.graph.nodes.analysis import analyze_vision_node

        state = CadJobState(
            job_id="timeout-4",
            input_type="drawing",
            image_path="/tmp/test.jpg",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._run_analyze_vision",
            side_effect=asyncio.TimeoutError(),
        ):
            result = await analyze_vision_node(state)

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_vision_timeout_does_not_hang(self) -> None:
        """Vision node should return promptly on timeout."""
        from backend.graph.nodes.analysis import analyze_vision_node

        state = CadJobState(
            job_id="timeout-5",
            input_type="drawing",
            image_path="/tmp/test.jpg",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._run_analyze_vision",
            side_effect=asyncio.TimeoutError(),
        ):
            result = await asyncio.wait_for(
                analyze_vision_node(state),
                timeout=5.0,
            )

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"


# ---------------------------------------------------------------------------
# Rate-limit and JSON errors (failure_reason mapping)
# ---------------------------------------------------------------------------

class TestFailureReasonMapping:
    """Verify map_exception_to_failure_reason covers all known error types."""

    @pytest.mark.asyncio
    async def test_rate_limit_maps_correctly(self) -> None:
        """HTTP 429 should map to failure_reason='rate_limited'."""
        from backend.graph.nodes.analysis import analyze_intent_node

        exc = Exception("Rate limited")
        exc.status_code = 429  # type: ignore[attr-defined]

        state = CadJobState(
            job_id="rate-1",
            input_type="text",
            input_text="make a gear",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=exc,
        ):
            result = await analyze_intent_node(state)

        assert result["failure_reason"] == "rate_limited"

    @pytest.mark.asyncio
    async def test_json_error_maps_correctly(self) -> None:
        """JSONDecodeError should map to failure_reason='invalid_json'."""
        import json

        from backend.graph.nodes.analysis import analyze_intent_node

        state = CadJobState(
            job_id="json-1",
            input_type="text",
            input_text="make a gear",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=json.JSONDecodeError("Expecting value", "", 0),
        ):
            result = await analyze_intent_node(state)

        assert result["failure_reason"] == "invalid_json"

    @pytest.mark.asyncio
    async def test_generic_error_maps_to_generation_error(self) -> None:
        """Unrecognized exceptions should map to 'generation_error'."""
        from backend.graph.nodes.analysis import analyze_intent_node

        state = CadJobState(
            job_id="gen-err-1",
            input_type="text",
            input_text="make a gear",
            status="created",
        )
        with patch(
            "backend.graph.nodes.analysis._parse_intent",
            new_callable=AsyncMock,
            side_effect=ValueError("Unexpected LLM output"),
        ):
            result = await analyze_intent_node(state)

        assert result["failure_reason"] == "generation_error"
