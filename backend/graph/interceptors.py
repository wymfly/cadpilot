"""InterceptorRegistry — build-time node insertion for the CAD pipeline.

Allows registering post-processing nodes that are inserted into the
StateGraph topology at build time. Interceptors are chained in registration
order within the same insertion point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class _InterceptorEntry:
    """A registered interceptor."""

    name: str
    node_fn: Callable[..., Awaitable[dict[str, Any]]]
    after: str  # node name to insert after


class InterceptorRegistry:
    """Registry for build-time pipeline node insertion."""

    def __init__(self) -> None:
        self._entries: list[_InterceptorEntry] = []

    def register(
        self,
        name: str,
        node_fn: Callable[..., Awaitable[dict[str, Any]]],
        after: str,
    ) -> None:
        """Register a node to be inserted after *after* in the workflow."""
        self._entries.append(_InterceptorEntry(name=name, node_fn=node_fn, after=after))

    def clear(self) -> None:
        """Remove all registered interceptors (useful for testing)."""
        self._entries.clear()

    def list_interceptors(self) -> list[dict[str, str]]:
        """Return a summary of registered interceptors."""
        return [{"name": e.name, "after": e.after} for e in self._entries]

    def apply(self, workflow: Any) -> None:
        """Insert registered interceptors into the StateGraph workflow.

        Only adds nodes; edge management is left to the builder.
        """
        for entry in self._entries:
            if entry.name not in workflow.nodes:
                workflow.add_node(entry.name, entry.node_fn)
                logger.info("Interceptor '%s' added after '%s'", entry.name, entry.after)


# Module-level default registry (empty — interceptors registered at app startup)
default_registry = InterceptorRegistry()
