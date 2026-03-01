"""Unified lifecycle decorator for graph nodes.

@timed_node automatically dispatches node.started / node.completed / node.failed
events, records elapsed time, and extracts _reasoning metadata from results.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from backend.graph.nodes.lifecycle import _safe_dispatch


def _summarize_outputs(result: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of node outputs for event payloads.

    - Filters out underscore-prefixed keys (metadata, not outputs)
    - Truncates long string values to 200 chars
    """
    summary: dict[str, Any] = {}
    for key, value in result.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        else:
            summary[key] = value
    return summary


def timed_node(node_name: str):
    """Wrap async graph nodes with lifecycle events + timing + reasoning."""

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            job_id = state.get("job_id", "unknown")
            t0 = time.time()

            await _safe_dispatch(
                "node.started",
                {
                    "job_id": job_id,
                    "node": node_name,
                    "timestamp": t0,
                },
            )

            try:
                result = await fn(state)
            except Exception as exc:
                elapsed = (time.time() - t0) * 1000
                await _safe_dispatch(
                    "node.failed",
                    {
                        "job_id": job_id,
                        "node": node_name,
                        "elapsed_ms": round(elapsed),
                        "error": str(exc),
                    },
                )
                raise

            elapsed = (time.time() - t0) * 1000
            reasoning = result.pop("_reasoning", None)

            await _safe_dispatch(
                "node.completed",
                {
                    "job_id": job_id,
                    "node": node_name,
                    "elapsed_ms": round(elapsed),
                    "reasoning": reasoning,
                    "outputs_summary": _summarize_outputs(result),
                },
            )

            return result

        return wrapper

    return decorator
