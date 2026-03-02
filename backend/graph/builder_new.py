"""New PipelineBuilder — dynamically generates StateGraph from resolved pipeline.

This file coexists with the legacy builder.py.  Activation is controlled by
the USE_NEW_BUILDER environment variable (default OFF).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.graph.context import NodeContext
from backend.graph.descriptor import NodeDescriptor
from backend.graph.pipeline_state import PipelineState
from backend.graph.resolver import DependencyResolver, ResolvedPipeline

logger = logging.getLogger(__name__)


async def _safe_dispatch(event_name: str, payload: dict[str, Any]) -> None:
    """Dispatch SSE event, tolerating missing run context."""
    try:
        from langchain_core.callbacks import adispatch_custom_event
        await adispatch_custom_event(event_name, payload)
    except RuntimeError:
        pass
    except Exception as exc:
        logger.warning("Event dispatch failed for %s: %s", event_name, exc)


def _summarize_outputs(diff: dict[str, Any], max_len: int = 500) -> dict[str, Any]:
    """Compact summary of node outputs for SSE payloads."""
    import json as _json

    summary: dict[str, Any] = {}
    for key, value in diff.items():
        if key.startswith("_") or key == "node_trace":
            continue
        if isinstance(value, str) and len(value) > 200:
            summary[key] = value[:200] + "..."
        elif isinstance(value, (dict, list)):
            try:
                serialized = _json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                serialized = str(value)
            if len(serialized) > max_len:
                if isinstance(value, dict):
                    summary[key] = {"_truncated": True, "keys": list(value.keys())[:20]}
                else:
                    summary[key] = {"_truncated": True, "length": len(value)}
            else:
                summary[key] = value
        elif value is not None:
            summary[key] = value
    return summary


class PipelineBuilder:
    """Build a LangGraph StateGraph from a ResolvedPipeline."""

    def build(self, resolved: ResolvedPipeline) -> StateGraph:
        workflow = StateGraph(PipelineState)

        # Register all nodes
        for desc in resolved.ordered_nodes:
            workflow.add_node(desc.name, self._wrap_node(desc))

        if not resolved.ordered_nodes:
            return workflow

        # Entry point
        entry = next((d for d in resolved.ordered_nodes if d.is_entry), None)
        if entry:
            workflow.add_edge(START, entry.name)
        else:
            workflow.add_edge(START, resolved.ordered_nodes[0].name)

        # Add conditional edges for input_type routing
        self._add_routing_edges(workflow, resolved)

        # Terminal nodes → END
        for desc in resolved.ordered_nodes:
            if desc.is_terminal:
                workflow.add_edge(desc.name, END)

        return workflow

    def _wrap_node(self, desc: NodeDescriptor):
        """Wrap a node function: NodeContext bridge + timing + SSE events."""

        async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            job_id = state.get("job_id", "unknown")
            t0 = time.time()

            await _safe_dispatch("node.started", {
                "job_id": job_id,
                "node": desc.name,
                "timestamp": t0,
            })

            try:
                ctx = NodeContext.from_state(state, desc)
                result = await desc.fn(ctx)
                elapsed_ms = round((time.time() - t0) * 1000)

                # Legacy nodes return dicts; new-style nodes return None
                if isinstance(result, dict):
                    diff = result
                else:
                    diff = ctx.to_state_diff()

                # Build trace entry
                reasoning = diff.pop("_reasoning", None)
                trace_entry = {
                    "node": desc.name,
                    "elapsed_ms": elapsed_ms,
                    "reasoning": reasoning,
                    "assets_produced": list(diff.get("assets", {}).keys()),
                }

                # Inject trace into diff
                if "node_trace" not in diff:
                    diff["node_trace"] = []
                diff["node_trace"].append(trace_entry)

                await _safe_dispatch("node.completed", {
                    "job_id": job_id,
                    "node": desc.name,
                    "elapsed_ms": elapsed_ms,
                    "reasoning": reasoning,
                    "outputs_summary": _summarize_outputs(diff),
                    "assets_produced": trace_entry["assets_produced"],
                })

                return diff

            except Exception as exc:
                elapsed_ms = round((time.time() - t0) * 1000)
                await _safe_dispatch("node.failed", {
                    "job_id": job_id,
                    "node": desc.name,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                })
                if desc.non_fatal:
                    logger.warning("Non-fatal node '%s' failed: %s", desc.name, exc)
                    return {"node_trace": [{
                        "node": desc.name,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                        "non_fatal": True,
                    }]}
                raise

        wrapped.__name__ = f"wrapped_{desc.name}"
        return wrapped

    def _add_routing_edges(
        self, workflow: StateGraph, resolved: ResolvedPipeline,
    ) -> None:
        """Add edges between nodes based on resolved topology.

        For nodes with multiple input_type-specific successors (e.g. create_job
        → analyze_intent | analyze_vision | analyze_organic), we use
        add_conditional_edges with input_type routing.

        For simple linear edges (single successor), we use add_edge.
        """
        # Build adjacency from resolved edges
        adjacency: dict[str, list[str]] = {}
        for src, dst in resolved.edges:
            adjacency.setdefault(src, []).append(dst)

        node_map = {d.name: d for d in resolved.ordered_nodes}

        for src_name, dst_names in adjacency.items():
            src_desc = node_map[src_name]
            if src_desc.is_terminal:
                continue  # terminal → END handled separately

            if len(dst_names) == 1:
                workflow.add_edge(src_name, dst_names[0])
            else:
                # Check if successors have distinct input_types → conditional routing
                input_type_map = self._build_input_type_routing(
                    dst_names, node_map,
                )
                if input_type_map:
                    # Need a routing function + possible fallback handling
                    routing_map = dict(input_type_map)
                    # Add conditional edge with routing function
                    workflow.add_conditional_edges(
                        src_name,
                        self._make_router(src_desc, input_type_map, node_map),
                        {name: name for name in dst_names},
                    )
                else:
                    # Same input_types — just fan out to first
                    # (shouldn't happen in practice with proper asset resolution)
                    workflow.add_edge(src_name, dst_names[0])

    def _build_input_type_routing(
        self,
        dst_names: list[str],
        node_map: dict[str, NodeDescriptor],
    ) -> list[tuple[str, str]] | None:
        """Build input_type → node_name mapping for conditional routing.

        Returns list of (input_type, node_name) tuples, or None if
        destinations don't have distinct input_types.
        """
        mapping: list[tuple[str, str]] = []
        seen_types: set[str] = set()

        for name in dst_names:
            desc = node_map[name]
            for it in desc.input_types:
                if it in seen_types:
                    return None  # overlap, can't use simple input_type routing
                seen_types.add(it)
                mapping.append((it, name))

        return mapping if mapping else None

    def _make_router(
        self,
        src_desc: NodeDescriptor,
        input_type_map: list[tuple[str, str]],
        node_map: dict[str, NodeDescriptor],
    ):
        """Create a routing function for conditional edges."""
        type_to_node = dict(input_type_map)
        all_dst = list(set(n for _, n in input_type_map))

        def router(state: dict[str, Any]) -> str:
            # Check for failure → route to terminal if available
            if state.get("status") == "failed":
                for desc in node_map.values():
                    if desc.is_terminal:
                        return desc.name
            input_type = state.get("input_type", "")
            return type_to_node.get(input_type, all_dst[0])

        return router


async def get_compiled_graph_new(
    pipeline_config: dict[str, dict] | None = None,
):
    """Compile graph with dynamic node discovery + dependency resolution.

    Unlike the legacy builder, this registers ALL nodes and uses
    conditional edges for input_type routing at runtime.
    """
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry

    discover_nodes()

    config = pipeline_config or {}
    resolved = DependencyResolver.resolve_all(registry, config)

    builder = PipelineBuilder()
    graph = builder.build(resolved)

    # Checkpointer
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = Path("backend/data/checkpoints.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = AsyncSqliteSaver.from_conn_string(str(db_path))
        await checkpointer.setup()
        logger.info("Using persistent SQLite checkpointer at %s", db_path)
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.warning("Using MemorySaver (state lost on restart)")
    except Exception as exc:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.warning("SQLite checkpointer failed (%s), using MemorySaver", exc)

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=resolved.interrupt_before,
    )
    return compiled
