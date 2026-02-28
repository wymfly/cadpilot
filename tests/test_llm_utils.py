"""Tests for LLM chain builders and exception mapping."""

import asyncio
import json
from unittest.mock import MagicMock

from backend.graph.llm_utils import (
    build_intent_chain,
    build_vision_chain,
    map_exception_to_failure_reason,
)


class TestMapExceptionToFailureReason:
    def test_timeout(self) -> None:
        assert map_exception_to_failure_reason(asyncio.TimeoutError()) == "timeout"

    def test_rate_limited_with_status_code(self) -> None:
        exc = Exception("Rate limit exceeded")
        exc.status_code = 429  # type: ignore[attr-defined]
        assert map_exception_to_failure_reason(exc) == "rate_limited"

    def test_json_decode_error(self) -> None:
        exc = json.JSONDecodeError("Expecting value", "", 0)
        assert map_exception_to_failure_reason(exc) == "invalid_json"

    def test_generic_error(self) -> None:
        assert map_exception_to_failure_reason(ValueError("boom")) == "generation_error"

    def test_keyboard_interrupt_still_classified(self) -> None:
        assert map_exception_to_failure_reason(KeyboardInterrupt()) == "generation_error"


class TestBuildIntentChain:
    def test_returns_runnable_with_fallback(self) -> None:
        primary = MagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        primary.with_fallbacks = MagicMock(return_value=primary)
        fallback = MagicMock()
        fallback.with_retry = MagicMock(return_value=fallback)
        chain = build_intent_chain(primary, fallback)
        primary.with_retry.assert_called_once()
        primary.with_fallbacks.assert_called_once()
        assert chain is not None

    def test_returns_runnable_without_fallback(self) -> None:
        primary = MagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        chain = build_intent_chain(primary)
        primary.with_retry.assert_called_once()
        assert chain is not None


class TestBuildVisionChain:
    def test_returns_runnable_no_fallback(self) -> None:
        primary = MagicMock()
        primary.with_retry = MagicMock(return_value=primary)
        chain = build_vision_chain(primary)
        primary.with_retry.assert_called_once()
        assert chain is not None
