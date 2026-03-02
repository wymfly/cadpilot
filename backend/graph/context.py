"""NodeContext — view layer over PipelineState for node implementations.

Nodes interact with state exclusively through NodeContext, never touching
the raw PipelineState dict directly.  This provides:
- Type-safe asset / data access
- Incremental state diff generation (to_state_diff returns only new entries)
- Event dispatch proxy
- Strategy instantiation
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from backend.graph.configs.base import BaseNodeConfig
from backend.graph.descriptor import NodeDescriptor, NodeStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AssetEntry + AssetRegistry
# ---------------------------------------------------------------------------

@dataclass
class AssetEntry:
    """A single artifact produced by a pipeline node."""

    key: str
    path: str
    format: str
    producer: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "format": self.format,
            "producer": self.producer,
            "metadata": self.metadata,
        }


class AssetRegistry:
    """In-memory registry of assets produced during a pipeline run."""

    def __init__(self) -> None:
        self._entries: dict[str, AssetEntry] = {}

    def put(
        self,
        key: str,
        path: str,
        format: str,
        producer: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._entries[key] = AssetEntry(
            key=key, path=path, format=format,
            producer=producer, metadata=metadata or {},
        )

    def get(self, key: str) -> AssetEntry:
        if key not in self._entries:
            raise KeyError(f"Asset not found: {key}")
        return self._entries[key]

    def has(self, key: str) -> bool:
        return key in self._entries

    def keys(self) -> list[str]:
        return list(self._entries.keys())

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {k: e.to_dict() for k, e in self._entries.items()}

    @classmethod
    def from_dict(cls, d: dict[str, dict[str, Any]]) -> AssetRegistry:
        reg = cls()
        for k, v in d.items():
            reg._entries[k] = AssetEntry(**v)
        return reg


# ---------------------------------------------------------------------------
# NodeContext
# ---------------------------------------------------------------------------

class NodeContext:
    """The sole interface nodes use to read/write pipeline state."""

    def __init__(
        self,
        job_id: str,
        input_type: str,
        assets: AssetRegistry,
        data: dict[str, Any],
        config: BaseNodeConfig,
        descriptor: NodeDescriptor,
        node_name: str,
        raw_state: dict[str, Any] | None = None,
    ) -> None:
        self.job_id = job_id
        self.input_type = input_type
        self._assets = assets
        self._data = data
        self.config = config
        self.descriptor = descriptor
        self.node_name = node_name
        self._state = raw_state or {}

        # Track incremental changes for to_state_diff()
        self._new_assets: dict[str, dict[str, Any]] = {}
        self._new_data: dict[str, Any] = {}
        self._trace_entries: list[dict[str, Any]] = []

    # -- Legacy dict-like access (backward compat for CadJobState nodes) --

    def __getitem__(self, key: str) -> Any:
        return self._state[key]

    def __contains__(self, key: str) -> bool:
        return key in self._state

    def get(self, key: str, default: Any = None) -> Any:  # noqa: D102
        return self._state.get(key, default)

    # -- Factory --

    @classmethod
    def from_state(cls, state: dict[str, Any], desc: NodeDescriptor) -> NodeContext:
        """Build a NodeContext from raw PipelineState dict."""
        assets = AssetRegistry.from_dict(state.get("assets", {}))
        data = copy.deepcopy(state.get("data", {}))

        node_configs = state.get("pipeline_config", {})
        raw_config = node_configs.get(desc.name, {})
        config_cls = desc.config_model or BaseNodeConfig
        config = config_cls(**raw_config) if raw_config else config_cls()

        return cls(
            job_id=state.get("job_id", ""),
            input_type=state.get("input_type", ""),
            assets=assets,
            data=data,
            config=config,
            descriptor=desc,
            node_name=desc.name,
            raw_state=state,
        )

    # -- Asset access --

    def get_asset(self, key: str) -> AssetEntry:
        return self._assets.get(key)

    def put_asset(
        self,
        key: str,
        path: str,
        format: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._assets.put(key, path, format, self.node_name, metadata)
        self._new_assets[key] = self._assets.get(key).to_dict()

    def has_asset(self, key: str) -> bool:
        return self._assets.has(key)

    # -- Data access --

    def get_data(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def put_data(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._new_data[key] = value

    # -- Strategy --

    def get_strategy(self) -> NodeStrategy:
        """Instantiate the strategy selected by current config."""
        strategy_name = self.config.strategy
        strategies = self.descriptor.strategies
        if not strategies:
            raise ValueError(f"Node '{self.node_name}' has no strategies defined")
        if strategy_name not in strategies:
            raise ValueError(
                f"Strategy '{strategy_name}' not found for '{self.node_name}'. "
                f"Available: {list(strategies.keys())}"
            )
        instance = strategies[strategy_name](config=self.config)
        if not instance.check_available():
            raise RuntimeError(
                f"Strategy '{strategy_name}' is not available "
                f"(runtime dependency missing)"
            )
        return instance

    # -- Event dispatch --

    async def dispatch(self, event_type: str, payload: dict[str, Any]) -> None:
        """Dispatch a custom SSE event (proxy for adispatch_custom_event)."""
        try:
            from langchain_core.callbacks import adispatch_custom_event
            await adispatch_custom_event(event_type, {"job_id": self.job_id, **payload})
        except RuntimeError:
            pass  # No parent run context (unit tests)
        except Exception as exc:
            logger.warning("Event dispatch failed for %s: %s", event_type, exc)

    async def dispatch_progress(
        self, current: int, total: int, message: str = "",
    ) -> None:
        await self.dispatch("job.progress", {
            "node": self.node_name,
            "current": current,
            "total": total,
            "message": message,
        })

    # -- State diff --

    def to_state_diff(self) -> dict[str, Any]:
        """Return only the incremental changes this node made.

        Works with PipelineState's custom _merge_dicts reducer —
        LangGraph merges these dicts into the existing state.
        """
        diff: dict[str, Any] = {}
        if self._new_assets:
            diff["assets"] = self._new_assets
        if self._new_data:
            diff["data"] = self._new_data
        if self._trace_entries:
            diff["node_trace"] = self._trace_entries
        return diff

    # -- Trace --

    def add_trace(self, entry: dict[str, Any]) -> None:
        self._trace_entries.append(entry)
