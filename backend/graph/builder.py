"""PipelineBuilder — dynamically generates StateGraph from resolved pipeline."""

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


def _last_completed_node(node_trace: list[dict[str, Any]]) -> str | None:
    """Return the name of the last non-skipped node in trace.

    R3-C3-1 fix: skip entries with {"skipped": True} to avoid
    disabled nodes causing breakpoint misses.
    """
    for entry in reversed(node_trace):
        if not entry.get("skipped"):
            return entry["node"]
    return None


class PipelineBuilder:
    """Build a LangGraph StateGraph from a ResolvedPipeline."""

    def build(
        self,
        resolved: ResolvedPipeline,
        interceptor_registry: Any = None,
    ) -> StateGraph:
        workflow = StateGraph(PipelineState)

        # Register all nodes
        for desc in resolved.ordered_nodes:
            workflow.add_node(desc.name, self._wrap_node(desc))

        # Apply interceptors (register nodes to workflow)
        if interceptor_registry is not None:
            interceptor_registry.apply(workflow)

        if not resolved.ordered_nodes:
            return workflow

        # Entry point
        entry = next((d for d in resolved.ordered_nodes if d.is_entry), None)
        if entry:
            workflow.add_edge(START, entry.name)
        else:
            workflow.add_edge(START, resolved.ordered_nodes[0].name)

        # Collect edges to skip (intercepted by interceptor chains)
        intercepted_edges: set[tuple[str, str]] = set()
        if interceptor_registry is not None:
            intercepted_edges = self._get_intercepted_edges(
                resolved, interceptor_registry,
            )

        # Add conditional edges for input_type routing (skipping intercepted)
        self._add_routing_edges(workflow, resolved, intercepted_edges)

        # Insert interceptor edge chains (explicit declaration)
        if interceptor_registry is not None:
            self._insert_interceptor_edges(workflow, resolved, interceptor_registry)

        # Terminal nodes → guard → END (R3 guard node architecture)
        guard = self._make_bp_guard()
        for desc in resolved.ordered_nodes:
            if desc.is_terminal:
                guard_name = f"__bp_guard_{desc.name}__"
                workflow.add_node(guard_name, guard)
                workflow.add_edge(desc.name, guard_name)
                workflow.add_edge(guard_name, END)

        return workflow

    def _wrap_node(self, desc: NodeDescriptor):
        """Wrap a node function: NodeContext bridge + timing + SSE events + breakpoints."""

        async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
            job_id = state.get("job_id", "unknown")

            # ── Disabled check FIRST (R2-G2-3: before breakpoint check) ──
            node_cfg = (state.get("pipeline_config") or {}).get(desc.name, {})
            if not node_cfg.get("enabled", True):
                logger.info("Node %s skipped (disabled)", desc.name)
                await _safe_dispatch("node.skipped", {
                    "job_id": job_id,
                    "node": desc.name,
                    "reason": "disabled",
                })
                # R2-G2-3: write skip trace to advance node_trace
                return {"node_trace": [{
                    "node": desc.name,
                    "skipped": True,
                    "elapsed_ms": 0,
                    "assets_produced": [],
                }]}

            # ── Pre-execution breakpoint (OUTSIDE try/except) ──
            bp_list = state.get("breakpoints") or []
            breakpoint_update: dict[str, Any] = {}
            if bp_list:
                node_trace = state.get("node_trace") or []
                last_completed = _last_completed_node(node_trace)
                if last_completed and (last_completed in bp_list or "__all__" in bp_list):
                    from langgraph.types import interrupt

                    await _safe_dispatch("node.breakpoint", {
                        "job_id": job_id,
                        "paused_after": last_completed,
                        "next_node": desc.name,
                    })

                    resume_val = interrupt({
                        "paused_after": last_completed,
                        "next_node": desc.name,
                        "status": "breakpoint",
                    })

                    if isinstance(resume_val, dict) and "action" in resume_val:
                        action = resume_val["action"]
                        if action == "step":
                            breakpoint_update["breakpoints"] = ["__all__"]
                        elif action == "run":
                            breakpoint_update["breakpoints"] = []

            # ── Normal execution (existing code structure) ──
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

                if isinstance(result, dict):
                    diff = result
                else:
                    diff = ctx.to_state_diff()

                reasoning = diff.pop("_reasoning", None)
                trace_entry = {
                    "node": desc.name,
                    "elapsed_ms": elapsed_ms,
                    "reasoning": reasoning,
                    "assets_produced": list(diff.get("assets", {}).keys()),
                }
                if hasattr(ctx, '_fallback_trace') and ctx._fallback_trace:
                    trace_entry["fallback"] = ctx._fallback_trace

                if "node_trace" not in diff:
                    diff["node_trace"] = []
                diff["node_trace"].append(trace_entry)

                if breakpoint_update:
                    diff.update(breakpoint_update)

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
                    diff = {"node_trace": [{
                        "node": desc.name,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                        "non_fatal": True,
                    }]}
                    # R3-G3-3 fix: preserve breakpoint state update
                    if breakpoint_update:
                        diff.update(breakpoint_update)
                    return diff
                raise

        wrapped.__name__ = f"wrapped_{desc.name}"
        return wrapped

    def _make_bp_guard(self) -> Any:
        """Create a lightweight breakpoint guard node for terminal → END."""

        async def bp_guard(state: dict[str, Any]) -> dict[str, Any]:
            bp_list = state.get("breakpoints") or []
            if not bp_list:
                return {}

            node_trace = state.get("node_trace") or []
            last_completed = _last_completed_node(node_trace)
            if last_completed and (last_completed in bp_list or "__all__" in bp_list):
                from langgraph.types import interrupt

                job_id = state.get("job_id", "unknown")
                await _safe_dispatch("node.breakpoint", {
                    "job_id": job_id,
                    "paused_after": last_completed,
                    "next_node": "__end__",
                })

                resume_val = interrupt({
                    "paused_after": last_completed,
                    "next_node": "__end__",
                    "status": "breakpoint",
                })

                if isinstance(resume_val, dict):
                    action = resume_val.get("action")
                    if action == "run":
                        return {"breakpoints": []}
                    # R4-P2-A: "step" at terminal = continue (no next node).
                    # Guard returns {} → graph proceeds to END normally.
            return {}

        bp_guard.__name__ = "__bp_guard__"
        return bp_guard

    def _get_intercepted_edges(
        self,
        resolved: ResolvedPipeline,
        interceptor_registry: Any,
    ) -> set[tuple[str, str]]:
        """Return set of (src, dst) edges that will be replaced by interceptor chains."""
        entries = interceptor_registry.list_interceptors()
        if not entries:
            return set()

        by_after: dict[str, list[str]] = {}
        for entry in entries:
            by_after.setdefault(entry["after"], []).append(entry["name"])

        adjacency: dict[str, list[str]] = {}
        for src, dst in resolved.edges:
            adjacency.setdefault(src, []).append(dst)

        intercepted: set[tuple[str, str]] = set()
        for after_node in by_after:
            successors = adjacency.get(after_node, [])
            if successors:
                intercepted.add((after_node, successors[0]))
        return intercepted

    def _add_routing_edges(
        self, workflow: StateGraph, resolved: ResolvedPipeline,
        intercepted_edges: set[tuple[str, str]] | None = None,
    ) -> None:
        """Add edges between nodes based on resolved topology.

        For nodes with multiple input_type-specific successors (e.g. create_job
        → analyze_intent | analyze_vision | analyze_organic), we use
        add_conditional_edges with input_type routing.

        For simple linear edges (single successor), we use add_edge.

        For multiple successors with overlapping input_types, we check
        reachability: if all skipped nodes are reachable from the earliest
        successor (transitive edges from OR deps), connect only to the
        earliest.  Otherwise, fan-out to all unreachable nodes.
        """
        # Build adjacency from resolved edges
        adjacency: dict[str, list[str]] = {}
        for src, dst in resolved.edges:
            adjacency.setdefault(src, []).append(dst)

        # Full adjacency for reachability checks
        full_adj: dict[str, set[str]] = {}
        for src, dst in resolved.edges:
            full_adj.setdefault(src, set()).add(dst)

        node_map = {d.name: d for d in resolved.ordered_nodes}
        topo_order = {d.name: i for i, d in enumerate(resolved.ordered_nodes)}

        skip = intercepted_edges or set()

        for src_name, dst_names in adjacency.items():
            src_desc = node_map[src_name]
            if src_desc.is_terminal:
                continue  # terminal → END handled separately

            # Filter out intercepted edges (will be replaced by chains)
            effective_dsts = [
                d for d in dst_names if (src_name, d) not in skip
            ]
            if not effective_dsts:
                # All edges intercepted — chains will be added later
                continue

            if len(effective_dsts) == 1:
                workflow.add_edge(src_name, effective_dsts[0])
            else:
                # Check if successors have distinct input_types → conditional routing
                input_type_map = self._build_input_type_routing(
                    effective_dsts, node_map,
                )
                if input_type_map:
                    # Need a routing function + possible fallback handling
                    workflow.add_conditional_edges(
                        src_name,
                        self._make_router(src_desc, input_type_map, node_map),
                        {name: name for name in effective_dsts},
                    )
                else:
                    # Overlapping input_types — check reachability to decide
                    # single edge vs fan-out.
                    first = min(effective_dsts, key=lambda n: topo_order.get(n, float("inf")))

                    # BFS from first to find reachable nodes
                    reachable: set[str] = set()
                    stack = [first]
                    while stack:
                        current = stack.pop()
                        for nxt in full_adj.get(current, set()):
                            if nxt not in reachable:
                                reachable.add(nxt)
                                stack.append(nxt)

                    unreachable = [n for n in effective_dsts if n != first and n not in reachable]

                    if not unreachable:
                        # All skipped nodes reachable from first — single edge
                        workflow.add_edge(src_name, first)
                        if len(effective_dsts) > 1:
                            skipped = [n for n in effective_dsts if n != first]
                            logger.debug(
                                "Node '%s': connecting to '%s' (earliest successor); "
                                "%s reachable through dependency chain",
                                src_name, first, skipped,
                            )
                    else:
                        # Some nodes NOT reachable — fan-out
                        fan_out_targets = sorted(
                            [first] + unreachable,
                            key=lambda n: topo_order.get(n, float("inf")),
                        )
                        self._add_fan_out(
                            workflow, src_name, fan_out_targets, node_map,
                        )
                        logger.debug(
                            "Node '%s': fan-out to %s (unreachable from '%s': %s)",
                            src_name, fan_out_targets, first, unreachable,
                        )

    def _add_fan_out(
        self,
        workflow: StateGraph,
        src_name: str,
        targets: list[str],
        node_map: dict[str, NodeDescriptor],
    ) -> None:
        """Add fan-out edges from src to multiple targets (parallel execution)."""
        terminal = next(
            (d.name for d in node_map.values() if d.is_terminal), None,
        )
        frozen_targets = list(targets)

        def router(state: dict[str, Any]) -> list[str] | str:
            if state.get("status") == "failed" and terminal:
                return terminal
            return frozen_targets

        path_map = {name: name for name in targets}
        if terminal and terminal not in path_map:
            path_map[terminal] = terminal
        workflow.add_conditional_edges(src_name, router, path_map)

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
        all_dst = sorted(set(n for _, n in input_type_map))

        def router(state: dict[str, Any]) -> str:
            # Check for failure → route to terminal if available
            if state.get("status") == "failed":
                for desc in node_map.values():
                    if desc.is_terminal:
                        return desc.name
            input_type = state.get("input_type", "")
            return type_to_node.get(input_type, all_dst[0])

        return router

    def _insert_interceptor_edges(
        self,
        workflow: StateGraph,
        resolved: ResolvedPipeline,
        interceptor_registry: Any,
    ) -> None:
        """Insert interceptor chains by explicit declaration.

        For each insertion point (e.g. after="convert_preview"), build a chain:
        convert_preview → int1 → int2 → ... → next_node
        """
        entries = interceptor_registry.list_interceptors()
        if not entries:
            return

        # Group interceptors by insertion point
        by_after: dict[str, list[str]] = {}
        for entry in entries:
            by_after.setdefault(entry["after"], []).append(entry["name"])

        # Build adjacency from resolved edges for reference
        resolved_successors: dict[str, list[str]] = {}
        for src, dst in resolved.edges:
            resolved_successors.setdefault(src, []).append(dst)

        for after_node, interceptor_names in by_after.items():
            successors = resolved_successors.get(after_node, [])
            if not successors:
                logger.warning(
                    "Interceptor insertion point '%s' has no successors "
                    "in resolved pipeline", after_node,
                )
                continue

            # For now, support single successor at insertion point
            next_node = successors[0]
            if len(successors) > 1:
                logger.warning(
                    "Interceptor insertion point '%s' has %d successors; "
                    "using first ('%s'). Others: %s",
                    after_node, len(successors), next_node, successors[1:],
                )

            # Direct edge (after_node → next_node) was already skipped in
            # _add_routing_edges via intercepted_edges set.

            # Build chain: after_node → int1 → int2 → ... → next_node
            chain = [after_node] + interceptor_names + [next_node]
            for i in range(len(chain) - 1):
                workflow.add_edge(chain[i], chain[i + 1])

            logger.info(
                "Interceptor chain inserted: %s (direct edge %s→%s removed)",
                " → ".join(chain), after_node, next_node,
            )


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

    from backend.graph.interceptors import default_registry

    builder = PipelineBuilder()
    graph = builder.build(resolved, interceptor_registry=default_registry)

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
