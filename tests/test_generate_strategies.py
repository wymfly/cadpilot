"""Tests for TripoSG, TRELLIS2, Hunyuan3D generate strategies."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_config(**kwargs):
    """Build a mock config with given attributes."""
    config = MagicMock()
    for k, v in kwargs.items():
        setattr(config, k, v)
    return config


class TestTripoSGStrategy:

    def test_available_when_endpoint_healthy(self):
        from backend.graph.strategies.generate.triposg import TripoSGGenerateStrategy
        strategy = TripoSGGenerateStrategy(
            config=_mock_config(triposg_endpoint="http://localhost:8081", timeout=120)
        )
        with patch.object(strategy, "_check_endpoint_health", return_value=True):
            assert strategy.check_available() is True

    def test_unavailable_when_no_endpoint(self):
        from backend.graph.strategies.generate.triposg import TripoSGGenerateStrategy
        strategy = TripoSGGenerateStrategy(
            config=_mock_config(triposg_endpoint=None, timeout=120)
        )
        assert strategy.check_available() is False

    @pytest.mark.asyncio
    async def test_execute_sends_empty_params(self):
        from backend.graph.strategies.generate.triposg import TripoSGGenerateStrategy
        strategy = TripoSGGenerateStrategy(
            config=_mock_config(
                triposg_endpoint="http://localhost:8081",
                timeout=330,
                output_format="glb",
            )
        )
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.get_data.return_value = {}
        ctx.get.return_value = None
        ctx.dispatch_progress = AsyncMock()

        with patch.object(
            strategy, "_post_generate",
            new_callable=AsyncMock,
            return_value=(b"glb-data", "model/gltf-binary", {"vertices": "100", "faces": "200", "watertight": True}),
        ) as mock_post:
            await strategy.execute(ctx)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {}
        assert call_kwargs["image_b64"] is None
        ctx.put_asset.assert_called_once()


class TestTRELLIS2Strategy:

    @pytest.mark.asyncio
    async def test_execute_sends_simplify_and_no_texture(self):
        from backend.graph.strategies.generate.trellis2 import TRELLIS2GenerateStrategy
        strategy = TRELLIS2GenerateStrategy(
            config=_mock_config(
                trellis2_endpoint="http://localhost:8082",
                timeout=330,
                output_format="glb",
            )
        )
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.get_data.return_value = {}
        ctx.get.return_value = None
        ctx.dispatch_progress = AsyncMock()

        with patch.object(
            strategy, "_post_generate",
            new_callable=AsyncMock,
            return_value=(b"glb-data", "model/gltf-binary", {}),
        ) as mock_post:
            await strategy.execute(ctx)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {"simplify": 100000, "texture": False}


class TestHunyuan3DStrategy:

    def test_available_local_only(self):
        """After rewrite, Hunyuan3D is local-only (no SaaS fallback)."""
        from backend.graph.strategies.generate.hunyuan3d import Hunyuan3DGenerateStrategy
        strategy = Hunyuan3DGenerateStrategy(
            config=_mock_config(hunyuan3d_endpoint="http://localhost:8080", timeout=120)
        )
        with patch.object(strategy, "_check_endpoint_health", return_value=True):
            assert strategy.check_available() is True

    def test_unavailable_without_endpoint(self):
        from backend.graph.strategies.generate.hunyuan3d import Hunyuan3DGenerateStrategy
        strategy = Hunyuan3DGenerateStrategy(
            config=_mock_config(hunyuan3d_endpoint=None, timeout=120)
        )
        assert strategy.check_available() is False

    @pytest.mark.asyncio
    async def test_execute_sends_no_texture(self):
        from backend.graph.strategies.generate.hunyuan3d import Hunyuan3DGenerateStrategy
        strategy = Hunyuan3DGenerateStrategy(
            config=_mock_config(
                hunyuan3d_endpoint="http://localhost:8080",
                timeout=330,
                output_format="glb",
            )
        )
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.get_data.return_value = {}
        ctx.get.return_value = None
        ctx.dispatch_progress = AsyncMock()

        with patch.object(
            strategy, "_post_generate",
            new_callable=AsyncMock,
            return_value=(b"glb-data", "model/gltf-binary", {}),
        ) as mock_post:
            await strategy.execute(ctx)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {"texture": False}
