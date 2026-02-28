"""LLM chain builders with retry, fallback, and timeout utilities."""

from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable


def map_exception_to_failure_reason(exc: BaseException) -> str:
    """Map an exception to a typed failure reason string."""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    status = getattr(exc, "status_code", None)
    if status == 429:
        return "rate_limited"
    return "generation_error"


def build_intent_chain(
    primary_llm: BaseChatModel,
    fallback_llm: BaseChatModel | None = None,
) -> Runnable:
    """Build an LCEL intent-parsing chain with retry + optional fallback."""
    chain = primary_llm.with_retry(
        stop_after_attempt=3,
        wait_exponential_jitter=True,
    )
    if fallback_llm is not None:
        fallback = fallback_llm.with_retry(
            stop_after_attempt=2,
            wait_exponential_jitter=True,
        )
        chain = chain.with_fallbacks([fallback])
    return chain


def build_vision_chain(primary_llm: BaseChatModel) -> Runnable:
    """Build an LCEL vision chain with retry only (no cheap VL fallback)."""
    return primary_llm.with_retry(
        stop_after_attempt=3,
        wait_exponential_jitter=True,
    )
