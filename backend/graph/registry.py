"""NodeRegistry — global registry of pipeline node descriptors.

Nodes self-register via the @register_node decorator at import time.
The registry is then consumed by DependencyResolver and PipelineBuilder.
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from backend.graph.descriptor import NodeDescriptor, NodeStrategy

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


class NodeRegistry:
    """Thread-safe singleton registry of NodeDescriptor instances."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeDescriptor] = {}

    def register(self, descriptor: NodeDescriptor) -> None:
        existing = self._nodes.get(descriptor.name)
        if existing is not None:
            # Idempotent: same function re-registering (module re-import) → skip
            if existing.fn is descriptor.fn:
                return
            raise ValueError(
                f"Node '{descriptor.name}' already registered "
                f"(existing fn: {existing.fn}, new fn: {descriptor.fn})"
            )
        self._nodes[descriptor.name] = descriptor
        logger.debug("Registered node: %s", descriptor.name)

    def get(self, name: str) -> NodeDescriptor:
        if name not in self._nodes:
            raise KeyError(f"Node not found: {name}")
        return self._nodes[name]

    def all(self) -> dict[str, NodeDescriptor]:
        return dict(self._nodes)

    def find_producers(self, asset: str) -> list[NodeDescriptor]:
        """Find all nodes that produce the given asset."""
        return [d for d in self._nodes.values() if asset in d.produces]

    def find_consumers(self, asset: str) -> list[NodeDescriptor]:
        """Find all nodes that require the given asset (AND or OR)."""
        result = []
        for d in self._nodes.values():
            for req in d.requires:
                if isinstance(req, str) and req == asset:
                    result.append(d)
                    break
                elif isinstance(req, list) and asset in req:
                    result.append(d)
                    break
        return result

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def _remove(self, name: str) -> None:
        """Remove a node (for testing only)."""
        self._nodes.pop(name, None)


# Module-level singleton
registry = NodeRegistry()


def register_node(
    *,
    name: str,
    display_name: str,
    requires: list[str | list[str]] | None = None,
    produces: list[str] | None = None,
    input_types: list[str] | None = None,
    config_model: type[BaseModel] | None = None,
    strategies: dict[str, type[NodeStrategy]] | None = None,
    default_strategy: str | None = None,
    is_entry: bool = False,
    is_terminal: bool = False,
    supports_hitl: bool = False,
    non_fatal: bool = False,
    description: str = "",
    estimated_duration: str = "",
) -> Callable:
    """Decorator that registers an async node function into the global registry."""

    def decorator(fn: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
        desc = NodeDescriptor(
            name=name,
            display_name=display_name,
            fn=fn,
            requires=requires or [],
            produces=produces or [],
            input_types=input_types or ["text", "drawing", "organic"],
            config_model=config_model,
            strategies=strategies or {},
            default_strategy=default_strategy,
            is_entry=is_entry,
            is_terminal=is_terminal,
            supports_hitl=supports_hitl,
            non_fatal=non_fatal,
            description=description,
            estimated_duration=estimated_duration,
        )
        registry.register(desc)

        # Attach descriptor to the function for introspection
        fn._node_descriptor = desc  # type: ignore[attr-defined]

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await fn(*args, **kwargs)

        wrapper._node_descriptor = desc  # type: ignore[attr-defined]
        return wrapper

    return decorator
