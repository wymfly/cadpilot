"""Cost optimization: model degradation strategy + result caching.

Provides two main capabilities:
1. ModelDegradationStrategy: selects cheaper models for later refine rounds
2. ResultCache: SHA256-keyed in-memory cache with TTL expiry

CostOptimizer combines both into a single facade.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Default degradation rules: role -> {round_num -> model_name}
_DEFAULT_RULES: dict[str, dict[int, str]] = {
    "vl": {1: "qwen-vl-max", 2: "qwen-vl-plus", 3: "qwen-vl-plus"},
    "coder": {1: "qwen-coder-plus", 2: "qwen-coder-plus", 3: "qwen-coder-plus"},
}


class ModelDegradationStrategy:
    """Select model name based on role and refine round number.

    Round 1 uses the most capable (expensive) model; later rounds may
    degrade to cheaper variants as defined by the rules dict.
    """

    def __init__(self, rules: Optional[dict[str, dict[int, str]]] = None) -> None:
        self._rules = rules if rules is not None else _DEFAULT_RULES

    def select_model(self, role: str, round_num: int) -> str:
        """Return model name for *role* at *round_num*.

        Falls back to the highest defined round when *round_num* exceeds
        the rule table.  If *role* is unknown, falls back to the default
        ``vl`` round-1 model.
        """
        role_rules = self._rules.get(role, {})
        if round_num in role_rules:
            return role_rules[round_num]
        # Fallback to highest defined round
        if role_rules:
            max_round = max(role_rules.keys())
            return role_rules[max_round]
        # Ultimate fallback for unknown roles
        return _DEFAULT_RULES.get("vl", {}).get(1, "qwen-vl-max")


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class ResultCache:
    """In-memory cache with TTL expiry and SHA256 key generation.

    Uses ``time.monotonic()`` for reliable, non-adjustable timing.
    Enforces a maximum size; oldest entries are evicted when full.
    """

    def __init__(
        self, ttl_seconds: float = 3600.0, max_size: int = 1000
    ) -> None:
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._store: dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def make_key(self, data: bytes) -> str:
        """Return SHA256 hex digest of *data*. Deterministic."""
        return hashlib.sha256(data).hexdigest()

    def set(self, key: str, value: Any) -> None:
        """Store *value* under *key* with TTL expiry."""
        if key not in self._store and len(self._store) >= self._max_size:
            # Evict the oldest entry (first inserted — dict preserves order)
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + self._ttl,
        )

    def get(self, key: str) -> Optional[Any]:
        """Retrieve value for *key*, or ``None`` if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def clear(self) -> None:
        """Remove all entries and reset stats."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, int]:
        """Return hit/miss/size counters."""
        return {"hits": self._hits, "misses": self._misses, "size": len(self._store)}


class CostOptimizer:
    """Facade combining model degradation + result caching."""

    def __init__(
        self,
        degradation: Optional[ModelDegradationStrategy] = None,
        cache_ttl: float = 3600.0,
    ) -> None:
        self._degradation = degradation or ModelDegradationStrategy()
        self._cache = ResultCache(ttl_seconds=cache_ttl)

    def get_model(self, role: str, round_num: int) -> str:
        """Select the model for *role* at *round_num*."""
        return self._degradation.select_model(role, round_num)

    def cache_result(self, image_data: bytes, result: Any) -> None:
        """Cache *result* keyed by SHA256 of *image_data*."""
        key = self._cache.make_key(image_data)
        self._cache.set(key, result)

    def get_cached_result(self, image_data: bytes) -> Optional[Any]:
        """Retrieve cached result for *image_data*, or ``None``."""
        key = self._cache.make_key(image_data)
        return self._cache.get(key)
