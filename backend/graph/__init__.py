"""LangGraph CAD Job orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.graph.builder import build_graph as build_graph
    from backend.graph.builder import get_compiled_graph as get_compiled_graph

__all__ = ["build_graph", "get_compiled_graph"]


def __getattr__(name: str):
    """Lazy import to avoid eagerly loading langgraph at module import time."""
    if name in __all__:
        from backend.graph import builder

        return getattr(builder, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
