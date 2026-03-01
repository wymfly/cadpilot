"""Unified lifecycle decorator for graph nodes.

@timed_node automatically dispatches node.started / node.completed / node.failed
events, records elapsed time, and extracts _reasoning metadata from results.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from backend.graph.nodes.lifecycle import _safe_dispatch


def _summarize_outputs(result: dict[str, Any], max_json_len: int = 500) -> dict[str, Any]:
    """Create a compact summary of node outputs for event payloads.

    - Filters out underscore-prefixed keys (metadata, not outputs)
    - Truncates long string values to 200 chars
    - Summarizes large dict/list values to avoid SSE payload bloat
    """
    import json as _json

    summary: dict[str, Any] = {}
    for key, value in result.items():
        if key.startswith("_"):
            continue
        if isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        elif isinstance(value, (dict, list)):
            try:
                serialized = _json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                serialized = str(value)
            if len(serialized) > max_json_len:
                if isinstance(value, dict):
                    summary[key] = {"_truncated": True, "keys": list(value.keys())[:20], "size": len(serialized)}
                else:
                    summary[key] = {"_truncated": True, "length": len(value), "size": len(serialized)}
            else:
                summary[key] = value
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
            if result is None:
                result = {}
            reasoning = result.get("_reasoning")
            clean_result = {k: v for k, v in result.items() if k != "_reasoning"}

            await _safe_dispatch(
                "node.completed",
                {
                    "job_id": job_id,
                    "node": node_name,
                    "elapsed_ms": round(elapsed),
                    "reasoning": reasoning,
                    "outputs_summary": _summarize_outputs(clean_result),
                },
            )

            return clean_result

        return wrapper

    return decorator
