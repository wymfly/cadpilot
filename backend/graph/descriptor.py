"""Node descriptors — declarative metadata for pipeline nodes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel


@dataclass
class NodeDescriptor:
    """Complete metadata for a registered pipeline node."""

    name: str
    display_name: str
    fn: Callable[..., Awaitable[dict[str, Any] | None]]

    # Dependency graph
    requires: list[str | list[str]] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    input_types: list[str] = field(default_factory=lambda: ["text", "drawing", "organic"])

    # Configuration
    config_model: type[BaseModel] | None = None
    strategies: dict[str, type[NodeStrategy]] = field(default_factory=dict)
    default_strategy: str | None = None
    fallback_chain: list[str] = field(default_factory=list)

    # Topology flags
    is_entry: bool = False
    is_terminal: bool = False
    supports_hitl: bool = False
    non_fatal: bool = False

    # Display
    description: str = ""
    estimated_duration: str = ""


@dataclass
class NodeResult:
    """Structured result metadata from a node execution."""

    assets_produced: list[str] = field(default_factory=list)
    data_produced: list[str] = field(default_factory=list)
    reasoning: dict[str, Any] = field(default_factory=dict)


class NodeStrategy(ABC):
    """Base class for pluggable node execution strategies."""

    def __init__(self, config=None):
        self.config = config

    @abstractmethod
    async def execute(self, ctx: Any) -> Any:
        """Execute the strategy with the given node context."""
        ...

    def check_available(self) -> bool:
        """Check if this strategy's runtime dependencies are available."""
        return True
