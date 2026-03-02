"""LangGraph CAD Job orchestration.

Supports two builder modes:
- New (default): dynamic graph from @register_node in builder_new.py
- Legacy (USE_NEW_BUILDER=0): hand-coded StateGraph in builder_legacy.py
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.graph.builder_legacy import build_graph as build_graph
    from backend.graph.builder_legacy import get_compiled_graph as get_compiled_graph

__all__ = ["build_graph", "get_compiled_graph"]


def __getattr__(name: str):
    """Lazy import to avoid eagerly loading langgraph at module import time."""
    if name in __all__:
        if os.environ.get("USE_NEW_BUILDER", "1") == "1":
            from backend.graph import builder_new

            if name == "get_compiled_graph":
                return builder_new.get_compiled_graph_new
            elif name == "build_graph":
                # For testing: build without checkpointer
                from backend.graph.discovery import discover_nodes
                from backend.graph.registry import registry
                from backend.graph.resolver import DependencyResolver

                def _build_graph():
                    discover_nodes()
                    resolved = DependencyResolver.resolve_all(registry, {})
                    return builder_new.PipelineBuilder().build(resolved).compile()

                return _build_graph
        else:
            from backend.graph import builder_legacy
            return getattr(builder_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
