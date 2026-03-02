"""Tests for NeuralStrategy base class with HTTP health check + cache."""

import pytest
from unittest.mock import patch, MagicMock

from backend.graph.configs.neural import NeuralStrategyConfig
from backend.graph.descriptor import NodeStrategy


class TestNeuralStrategyThreeStates:
    """Three-state design: disabled / available / degraded."""

    def test_disabled_when_not_enabled(self):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(neural_enabled=False)
        s = ConcreteNeural(config=cfg)
        assert s.check_available() is False

    def test_disabled_when_no_endpoint(self):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(neural_enabled=True, neural_endpoint=None)
        s = ConcreteNeural(config=cfg)
        assert s.check_available() is False

    @patch("backend.graph.strategies.neural.httpx")
    def test_available_when_health_ok(self, mock_httpx):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        )
        s = ConcreteNeural(config=cfg)
        assert s.check_available() is True
        mock_httpx.get.assert_called_once_with(
            "http://gpu:8090/health",
            timeout=5,
        )

    @patch("backend.graph.strategies.neural.httpx")
    def test_degraded_when_health_fails(self, mock_httpx):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_httpx.get.return_value = mock_resp

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        )
        s = ConcreteNeural(config=cfg)
        assert s.check_available() is False

    @patch("backend.graph.strategies.neural.httpx")
    def test_degraded_when_http_exception(self, mock_httpx):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        mock_httpx.get.side_effect = Exception("connection refused")

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        )
        s = ConcreteNeural(config=cfg)
        assert s.check_available() is False


class TestHealthCheckCache:
    """Cache is class/module-level, keyed by (endpoint, health_check_path)."""

    @patch("backend.graph.strategies.neural.httpx")
    def test_cache_hit_within_ttl(self, mock_httpx):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        )
        s1 = ConcreteNeural(config=cfg)
        assert s1.check_available() is True

        # Second call on different instance — should use cache
        s2 = ConcreteNeural(config=cfg)
        assert s2.check_available() is True
        assert mock_httpx.get.call_count == 1

    @patch("backend.graph.strategies.neural.httpx")
    def test_cache_expired_triggers_new_check(self, mock_httpx):
        from backend.graph.strategies.neural import (
            NeuralStrategy,
            _health_cache,
            _CACHE_TTL,
        )
        import backend.graph.strategies.neural as neural_mod

        _health_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu:8090",
        )

        fake_time = [100.0]
        original_clock = neural_mod._clock
        neural_mod._clock = lambda: fake_time[0]

        try:
            s1 = ConcreteNeural(config=cfg)
            assert s1.check_available() is True
            assert mock_httpx.get.call_count == 1

            # Advance past TTL
            fake_time[0] = 100.0 + _CACHE_TTL + 1
            s2 = ConcreteNeural(config=cfg)
            assert s2.check_available() is True
            assert mock_httpx.get.call_count == 2
        finally:
            neural_mod._clock = original_clock

    @patch("backend.graph.strategies.neural.httpx")
    def test_different_endpoints_isolated(self, mock_httpx):
        from backend.graph.strategies.neural import NeuralStrategy, _health_cache

        _health_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_httpx.get.return_value = mock_resp

        class ConcreteNeural(NeuralStrategy):
            async def execute(self, ctx):
                return "neural"

        cfg1 = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu1:8090",
        )
        cfg2 = NeuralStrategyConfig(
            neural_enabled=True,
            neural_endpoint="http://gpu2:8090",
        )
        ConcreteNeural(config=cfg1).check_available()
        ConcreteNeural(config=cfg2).check_available()
        assert mock_httpx.get.call_count == 2


class TestNeuralStrategyInheritance:
    def test_is_subclass_of_node_strategy(self):
        from backend.graph.strategies.neural import NeuralStrategy

        assert issubclass(NeuralStrategy, NodeStrategy)
