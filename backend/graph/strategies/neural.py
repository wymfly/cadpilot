"""NeuralStrategy base class with HTTP health check and TTL cache."""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from typing import Any

import httpx

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level health check cache
# ---------------------------------------------------------------------------

_CACHE_TTL = 30  # seconds

# Injectable clock for testing
_clock = time.monotonic

# Cache: (endpoint, health_check_path) -> (result: bool, timestamp: float)
_health_cache: dict[tuple[str, str], tuple[bool, float]] = {}


class NeuralStrategy(NodeStrategy):
    """Base class for Neural channel strategies.

    Integrates HTTP health check into check_available() with
    class-level TTL cache. Three states: disabled, available, degraded.
    """

    def __init__(self, config=None):
        super().__init__(config)

    def check_available(self) -> bool:
        """Three-state check: disabled -> False, available -> True, degraded -> False."""
        if self.config is None:
            return False

        neural_enabled = getattr(self.config, "neural_enabled", False)
        neural_endpoint = getattr(self.config, "neural_endpoint", None)

        # Disabled state
        if not neural_enabled or not neural_endpoint:
            return False

        health_path = getattr(self.config, "health_check_path", "/health")
        cache_key = (neural_endpoint, health_path)

        # Check cache
        if cache_key in _health_cache:
            cached_result, cached_time = _health_cache[cache_key]
            if _clock() - cached_time < _CACHE_TTL:
                return cached_result

        # Perform health check
        url = f"{neural_endpoint.rstrip('/')}{health_path}"
        try:
            resp = httpx.get(url, timeout=5)
            result = resp.status_code == 200
        except Exception as exc:
            logger.warning("Health check failed for %s: %s", url, exc)
            result = False

        _health_cache[cache_key] = (result, _clock())
        return result

    @abstractmethod
    async def execute(self, ctx: Any) -> Any:
        """Subclasses implement the actual neural inference call."""
        ...
