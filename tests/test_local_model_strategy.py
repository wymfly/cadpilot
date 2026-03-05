"""Tests for LocalModelStrategy base class — JSON+base64 protocol."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_strategy():
    """Create a concrete LocalModelStrategy subclass for testing."""
    from backend.graph.strategies.generate.base import LocalModelStrategy

    class ConcreteStrategy(LocalModelStrategy):
        async def execute(self, ctx):
            pass

    strategy = ConcreteStrategy.__new__(ConcreteStrategy)
    strategy.config = MagicMock()
    return strategy


class TestPostGenerate:
    """Test _post_generate JSON+base64 protocol."""

    @pytest.mark.asyncio
    async def test_sends_json_body_with_image_seed_params(self):
        """Verify request body structure: {image, seed, params}."""
        strategy = _make_strategy()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake-glb-data"
        mock_response.headers = {
            "content-type": "model/gltf-binary",
            "X-Mesh-Vertices": "1000",
            "X-Mesh-Faces": "2000",
            "X-Mesh-Watertight": "true",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("backend.graph.strategies.generate.base.httpx.AsyncClient", return_value=mock_client):
            data, content_type, mesh_meta = await strategy._post_generate(
                endpoint="http://localhost:8081",
                image_b64="dGVzdA==",
                seed=42,
                params={"simplify": 100000},
                timeout=300,
            )

        # Verify JSON body
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["json"] == {
            "image": "dGVzdA==",
            "seed": 42,
            "params": {"simplify": 100000},
        }
        assert data == b"fake-glb-data"
        assert content_type == "model/gltf-binary"
        assert mesh_meta["watertight"] is True
        assert mesh_meta["vertices"] == "1000"

    @pytest.mark.asyncio
    async def test_watertight_false_string_parsed_correctly(self):
        """Verify bool('false') trap is avoided."""
        strategy = _make_strategy()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"data"
        mock_response.headers = {
            "content-type": "model/gltf-binary",
            "X-Mesh-Watertight": "false",
            "X-Mesh-Vertices": "0",
            "X-Mesh-Faces": "0",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("backend.graph.strategies.generate.base.httpx.AsyncClient", return_value=mock_client):
            _, _, mesh_meta = await strategy._post_generate(
                endpoint="http://localhost:8081",
                image_b64="dGVzdA==",
                timeout=300,
            )

        # bool("false") would be True — verify explicit parsing
        assert mesh_meta["watertight"] is False


class TestHealthCheck:
    """Test _check_endpoint_health."""

    def test_health_check_accepts_200_only(self):
        """Only status_code == 200 is healthy."""
        from backend.graph.strategies.generate.base import _health_cache

        _health_cache.clear()
        strategy = _make_strategy()
        strategy.config = MagicMock(timeout=120)

        mock_resp = MagicMock(status_code=200)
        with patch("backend.graph.strategies.generate.base.httpx.get", return_value=mock_resp):
            assert strategy._check_endpoint_health("http://localhost:8081") is True

    def test_health_check_rejects_redirect(self):
        """3xx redirect is NOT healthy."""
        from backend.graph.strategies.generate.base import _health_cache

        _health_cache.clear()
        strategy = _make_strategy()
        strategy.config = MagicMock(timeout=120)

        mock_resp = MagicMock(status_code=301)
        with patch("backend.graph.strategies.generate.base.httpx.get", return_value=mock_resp):
            assert strategy._check_endpoint_health("http://localhost:8081") is False


class TestRetryOn503:
    """Test 503 retry logic."""

    @pytest.mark.asyncio
    async def test_retries_once_on_503_with_retry_after(self):
        """503 with Retry-After triggers one retry."""
        strategy = _make_strategy()

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.headers = {"Retry-After": "1"}
        resp_503.raise_for_status = MagicMock(side_effect=Exception("503"))

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.content = b"glb"
        resp_200.headers = {
            "content-type": "model/gltf-binary",
            "X-Mesh-Vertices": "100",
            "X-Mesh-Faces": "200",
            "X-Mesh-Watertight": "true",
        }
        resp_200.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=[resp_503, resp_200])

        with patch("backend.graph.strategies.generate.base.httpx.AsyncClient", return_value=mock_client):
            with patch("backend.graph.strategies.generate.base.asyncio.sleep", new_callable=AsyncMock):
                data, _, _ = await strategy._post_generate(
                    endpoint="http://localhost:8081",
                    image_b64="dGVzdA==",
                    timeout=300,
                )

        assert data == b"glb"
        assert mock_client.post.call_count == 2


class TestGetImageB64:
    """Test _get_image_b64 static method."""

    def test_returns_none_when_no_reference(self):
        from backend.graph.strategies.generate.base import LocalModelStrategy

        ctx = MagicMock()
        ctx.get.return_value = None
        assert LocalModelStrategy._get_image_b64(ctx) is None

    def test_encodes_bytes_to_base64(self):
        import base64

        from backend.graph.strategies.generate.base import LocalModelStrategy

        ctx = MagicMock()
        ctx.get.return_value = b"image-data"
        result = LocalModelStrategy._get_image_b64(ctx)
        assert result == base64.b64encode(b"image-data").decode()

    def test_short_string_raises_when_file_not_found(self):
        from backend.graph.strategies.generate.base import LocalModelStrategy

        ctx = MagicMock()
        ctx.get.return_value = "abc123"  # short file_id

        with pytest.raises(RuntimeError, match="file not found"):
            LocalModelStrategy._get_image_b64(ctx)

    def test_long_string_assumed_base64(self):
        from backend.graph.strategies.generate.base import LocalModelStrategy

        ctx = MagicMock()
        long_b64 = "A" * 200  # long string = already base64
        ctx.get.return_value = long_b64
        assert LocalModelStrategy._get_image_b64(ctx) == long_b64
