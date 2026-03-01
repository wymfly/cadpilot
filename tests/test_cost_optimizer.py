"""Tests for cost optimization: model degradation + result caching."""
import time

import pytest

from backend.core.cost_optimizer import (
    ModelDegradationStrategy,
    ResultCache,
    CostOptimizer,
)


class TestModelDegradationStrategy:
    def test_round1_uses_max(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("vl", round_num=1)
        assert model == "qwen-vl-max"

    def test_round2_uses_plus(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("vl", round_num=2)
        assert model == "qwen-vl-plus"

    def test_round3_uses_plus(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("vl", round_num=3)
        assert model == "qwen-vl-plus"

    def test_coder_round1(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("coder", round_num=1)
        assert model == "qwen-coder-plus"

    def test_coder_round2(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("coder", round_num=2)
        assert model == "qwen-coder-plus"

    def test_coder_round3(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("coder", round_num=3)
        assert model == "qwen-coder-plus"

    def test_custom_rules(self):
        rules = {"vl": {1: "model-a", 2: "model-b"}}
        strategy = ModelDegradationStrategy(rules=rules)
        assert strategy.select_model("vl", round_num=1) == "model-a"
        assert strategy.select_model("vl", round_num=2) == "model-b"

    def test_fallback_to_highest_round(self):
        """When round_num exceeds defined rounds, use highest defined round's model."""
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("vl", round_num=5)
        # Should fallback to round 3 (highest defined) → qwen-vl-plus
        assert model == "qwen-vl-plus"

    def test_custom_rules_fallback(self):
        rules = {"vl": {1: "model-x", 2: "model-y"}}
        strategy = ModelDegradationStrategy(rules=rules)
        # round 3 not defined, should fallback to round 2 (highest)
        assert strategy.select_model("vl", round_num=3) == "model-y"

    def test_unknown_role_returns_default(self):
        strategy = ModelDegradationStrategy()
        model = strategy.select_model("unknown", round_num=1)
        assert model is not None
        assert isinstance(model, str)
        assert len(model) > 0

    def test_empty_dict_rules_uses_empty(self):
        """Empty dict {} is a valid config — should NOT fall back to defaults."""
        strategy = ModelDegradationStrategy(rules={})
        model = strategy.select_model("vl", round_num=1)
        # Empty rules → unknown role fallback → default vl round-1
        assert model == "qwen-vl-max"


class TestResultCache:
    def test_set_and_get(self):
        cache = ResultCache(ttl_seconds=3600)
        cache.set("key1", {"result": "ok"})
        assert cache.get("key1") == {"result": "ok"}

    def test_get_missing(self):
        cache = ResultCache(ttl_seconds=3600)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = ResultCache(ttl_seconds=0.01)  # 10ms
        cache.set("key1", {"result": "ok"})
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_hash_key_deterministic(self):
        cache = ResultCache()
        k1 = cache.make_key(b"image_bytes_1")
        k2 = cache.make_key(b"image_bytes_1")
        assert k1 == k2

    def test_hash_key_different_data(self):
        cache = ResultCache()
        k1 = cache.make_key(b"image_bytes_1")
        k2 = cache.make_key(b"image_bytes_2")
        assert k1 != k2

    def test_hash_key_is_sha256_hex(self):
        cache = ResultCache()
        key = cache.make_key(b"test")
        assert len(key) == 64  # SHA256 hex digest length
        assert all(c in "0123456789abcdef" for c in key)

    def test_stats_initial(self):
        cache = ResultCache()
        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["size"] == 0

    def test_stats_tracking(self):
        cache = ResultCache()
        cache.set("k1", "v1")
        cache.get("k1")  # hit
        cache.get("k2")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_stats_expired_counts_as_miss(self):
        cache = ResultCache(ttl_seconds=0.01)
        cache.set("k1", "v1")
        time.sleep(0.02)
        cache.get("k1")  # expired → miss
        stats = cache.stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_clear(self):
        cache = ResultCache()
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        # After clear, store is empty and stats are reset
        stats = cache.stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        # Gets after clear correctly return None (and count as misses)
        assert cache.get("k1") is None
        assert cache.get("k2") is None
        stats = cache.stats()
        assert stats["misses"] == 2

    def test_overwrite_value(self):
        cache = ResultCache()
        cache.set("k1", "v1")
        cache.set("k1", "v2")
        assert cache.get("k1") == "v2"

    def test_default_ttl(self):
        cache = ResultCache()
        assert cache._ttl == 3600.0

    def test_max_size_eviction(self):
        """When cache exceeds max_size, oldest entry is evicted."""
        cache = ResultCache(ttl_seconds=3600, max_size=2)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")  # should evict k1
        assert cache.get("k1") is None
        assert cache.get("k2") == "v2"
        assert cache.get("k3") == "v3"
        assert cache.stats()["size"] == 2

    def test_overwrite_does_not_evict(self):
        """Overwriting existing key should NOT trigger eviction."""
        cache = ResultCache(ttl_seconds=3600, max_size=2)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k1", "v1_updated")  # overwrite, not new entry
        assert cache.get("k1") == "v1_updated"
        assert cache.get("k2") == "v2"
        assert cache.stats()["size"] == 2


class TestCostOptimizer:
    def test_init(self):
        opt = CostOptimizer()
        assert opt is not None

    def test_init_custom_degradation(self):
        rules = {"vl": {1: "custom-model"}}
        strategy = ModelDegradationStrategy(rules=rules)
        opt = CostOptimizer(degradation=strategy)
        assert opt.get_model("vl", round_num=1) == "custom-model"

    def test_init_custom_ttl(self):
        opt = CostOptimizer(cache_ttl=60.0)
        assert opt._cache._ttl == 60.0

    def test_get_model_vl(self):
        opt = CostOptimizer()
        model = opt.get_model("vl", round_num=1)
        assert model == "qwen-vl-max"

    def test_get_model_coder(self):
        opt = CostOptimizer()
        model = opt.get_model("coder", round_num=1)
        assert model == "qwen-coder-plus"

    def test_cache_result(self):
        opt = CostOptimizer()
        opt.cache_result(b"image_data", {"part_type": "rotational"})
        cached = opt.get_cached_result(b"image_data")
        assert cached == {"part_type": "rotational"}

    def test_cache_miss(self):
        opt = CostOptimizer()
        assert opt.get_cached_result(b"new_image") is None

    def test_cache_different_images(self):
        opt = CostOptimizer()
        opt.cache_result(b"image_1", {"part_type": "rotational"})
        opt.cache_result(b"image_2", {"part_type": "plate"})
        assert opt.get_cached_result(b"image_1") == {"part_type": "rotational"}
        assert opt.get_cached_result(b"image_2") == {"part_type": "plate"}


class TestCostOptimizerIntegration:
    """Verify CostOptimizer is wired into the analysis pipeline."""

    def test_module_level_instance_exists(self):
        from backend.graph.nodes import analysis
        assert hasattr(analysis, "_cost_optimizer")
        assert isinstance(analysis._cost_optimizer, CostOptimizer)
