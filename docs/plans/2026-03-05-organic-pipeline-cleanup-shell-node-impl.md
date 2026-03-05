# 有机管道策略清理 + shell_node 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 清理废弃策略（tripo3d、spar3d），新增 TripoSG/TRELLIS.2 本地直连策略，改造 `LocalModelStrategy` 基类为 JSON+base64 协议，新增 shell_node 抽壳节点。

**Architecture:** 策略模式 + LangGraph 节点注册。`LocalModelStrategy` 基类提供统一的 HTTP 通信，三个具体策略仅差异化 endpoint 和默认 params。shell_node 在 mesh_scale 之后、boolean_assemble 之前插入，passthrough 模式零成本。

**Tech Stack:** Python 3.10+, Pydantic v2, httpx, trimesh, meshlib, LangGraph

**设计文档:** `docs/plans/2026-03-05-organic-pipeline-cleanup-shell-node.md`

**前置依赖:** GPU Server API 标准化完成（Task 1-6 of `2026-03-05-gpu-server-api-standardization-impl.md`）

---

## Task 1: 改造 LocalModelStrategy 基类

**目标:** 从 multipart/form-data 改为 JSON+base64 协议，增加 mesh 元信息解析和 503 重试。

**Files:**
- Modify: `backend/graph/strategies/generate/base.py`
- Test: `tests/test_local_model_strategy.py`

**Step 1: 编写测试**

```python
# tests/test_local_model_strategy.py
"""Tests for LocalModelStrategy base class — JSON+base64 protocol."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPostGenerate:
    """Test _post_generate JSON+base64 protocol."""

    @pytest.mark.asyncio
    async def test_sends_json_body_with_image_seed_params(self):
        """Verify request body structure: {image, seed, params}."""
        from backend.graph.strategies.generate.base import LocalModelStrategy

        strategy = LocalModelStrategy.__new__(LocalModelStrategy)
        strategy.config = MagicMock()

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
        from backend.graph.strategies.generate.base import LocalModelStrategy

        strategy = LocalModelStrategy.__new__(LocalModelStrategy)
        strategy.config = MagicMock()

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
        from backend.graph.strategies.generate.base import LocalModelStrategy, _health_cache

        _health_cache.clear()
        strategy = LocalModelStrategy.__new__(LocalModelStrategy)
        strategy.config = MagicMock(timeout=120)

        mock_resp = MagicMock(status_code=200)
        with patch("backend.graph.strategies.generate.base.httpx.get", return_value=mock_resp):
            assert strategy._check_endpoint_health("http://localhost:8081") is True

    def test_health_check_rejects_redirect(self):
        """3xx redirect is NOT healthy."""
        from backend.graph.strategies.generate.base import LocalModelStrategy, _health_cache

        _health_cache.clear()
        strategy = LocalModelStrategy.__new__(LocalModelStrategy)
        strategy.config = MagicMock(timeout=120)

        mock_resp = MagicMock(status_code=301)
        with patch("backend.graph.strategies.generate.base.httpx.get", return_value=mock_resp):
            assert strategy._check_endpoint_health("http://localhost:8081") is False


class TestRetryOn503:
    """Test 503 retry logic."""

    @pytest.mark.asyncio
    async def test_retries_once_on_503_with_retry_after(self):
        """503 with Retry-After triggers one retry."""
        from backend.graph.strategies.generate.base import LocalModelStrategy

        strategy = LocalModelStrategy.__new__(LocalModelStrategy)
        strategy.config = MagicMock()

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
```

**Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_local_model_strategy.py -v
```

Expected: FAIL（当前 `_post_generate` 签名和协议不匹配）

**Step 3: 重写 `base.py`**

将 `backend/graph/strategies/generate/base.py` 改为：

```python
"""LocalModelStrategy — base class for local HTTP model endpoints.

Provides:
- Health check with TTL cache: GET {endpoint}/health
- Generation POST: POST {endpoint}/v1/generate (JSON + base64)
- 503 retry with Retry-After budget check
- Output file saving helper
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any

import httpx

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level health check cache
# ---------------------------------------------------------------------------

_CACHE_TTL = 30  # seconds

# Cache: endpoint -> (result: bool, timestamp: float)
_health_cache: dict[str, tuple[bool, float]] = {}

# 503 retry constants
_RETRY_AFTER_DEFAULT = 30
_RETRY_AFTER_MAX = 120


class LocalModelStrategy(NodeStrategy):
    """Base class for strategies that call a local HTTP model endpoint.

    Subclasses implement execute() and use _check_endpoint_health() and
    _post_generate() to interact with the local model service.
    """

    def __init__(self, config=None):
        super().__init__(config)

    def _check_endpoint_health(self, endpoint: str) -> bool:
        """Check endpoint health via GET {endpoint}/health with TTL cache.

        Returns True if status 200, False otherwise. Results are cached
        for _CACHE_TTL seconds.
        """
        if endpoint in _health_cache:
            cached_result, cached_time = _health_cache[endpoint]
            if time.monotonic() - cached_time < _CACHE_TTL:
                return cached_result

        url = f"{endpoint.rstrip('/')}/health"
        timeout = getattr(self.config, "timeout", 120)
        check_timeout = min(timeout, 5)
        try:
            resp = httpx.get(url, timeout=check_timeout)
            result = resp.status_code == 200
        except Exception as exc:
            logger.warning("Health check failed for %s: %s", url, exc)
            result = False

        _health_cache[endpoint] = (result, time.monotonic())
        return result

    async def _post_generate(
        self,
        endpoint: str,
        image_b64: str | None = None,
        seed: int | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 330,
    ) -> tuple[bytes, str, dict[str, Any]]:
        """POST JSON to {endpoint}/v1/generate.

        Args:
            endpoint: Base URL of the local model service.
            image_b64: Base64-encoded reference image.
            seed: Random seed for reproducibility.
            params: Model-specific generation parameters.
            timeout: Single request timeout in seconds.

        Returns:
            Tuple of (response_bytes, content_type, mesh_meta).
            mesh_meta contains vertices, faces, watertight from response headers.
        """
        url = f"{endpoint.rstrip('/')}/v1/generate"
        body: dict[str, Any] = {"params": params or {}}
        if image_b64 is not None:
            body["image"] = image_b64
        if seed is not None:
            body["seed"] = seed

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body)

            # 503 retry logic — GPU busy, single retry with budget check
            # Budget: retry_after (wait) + timeout (next request) must fit within 2x timeout.
            # This means retry_after must be <= timeout. If GPU says "retry in 200s"
            # but our timeout is only 120s, the total 200+120=320s exceeds budget — fail fast.
            if resp.status_code == 503:
                retry_after = self._parse_retry_after(resp)
                if retry_after + timeout > timeout * 2:
                    raise RuntimeError(
                        f"GPU busy, Retry-After={retry_after}s exceeds budget"
                    )
                logger.info("GPU busy, retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                resp = await client.post(url, json=body)

            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "application/octet-stream")
            mesh_meta = {
                "vertices": resp.headers.get("X-Mesh-Vertices"),
                "faces": resp.headers.get("X-Mesh-Faces"),
                "watertight": resp.headers.get("X-Mesh-Watertight", "").lower() == "true",
            }
            return resp.content, content_type, mesh_meta

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> int:
        """Parse Retry-After header with safe defaults."""
        raw = resp.headers.get("Retry-After", "")
        try:
            value = int(raw)
            if value <= 0:
                return _RETRY_AFTER_DEFAULT
            return min(value, _RETRY_AFTER_MAX)
        except (ValueError, TypeError):
            return _RETRY_AFTER_DEFAULT

    @staticmethod
    def _save_output(
        data: bytes,
        job_id: str,
        suffix: str = ".glb",
        prefix: str = "generate",
    ) -> str:
        """Save raw mesh bytes to a temp file and return the path."""
        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / prefix
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_id}{suffix}"
        output_path.write_bytes(data)
        return str(output_path)

    @abstractmethod
    async def execute(self, ctx: Any) -> Any:
        """Subclasses implement the actual generation call."""
        ...
```

**Step 4: 运行测试，确认通过**

```bash
uv run pytest tests/test_local_model_strategy.py -v
```

**Step 5: Commit**

```bash
git add backend/graph/strategies/generate/base.py tests/test_local_model_strategy.py
git commit -m "feat(strategy): rewrite LocalModelStrategy to JSON+base64 protocol with 503 retry"
```

---

## Task 2: 删除废弃策略 + 创建新策略

**目标:** 删除 tripo3d/spar3d，新增 triposg/trellis2，重写 hunyuan3d（去 SaaS）。

**Files:**
- Delete: `backend/graph/strategies/generate/tripo3d.py`
- Delete: `backend/graph/strategies/generate/spar3d.py`
- Create: `backend/graph/strategies/generate/triposg.py`
- Create: `backend/graph/strategies/generate/trellis2.py`
- Modify: `backend/graph/strategies/generate/hunyuan3d.py`
- Modify: `backend/graph/strategies/generate/__init__.py`
- Test: `tests/test_generate_strategies.py`

**Step 1: 编写测试**

```python
# tests/test_generate_strategies.py
"""Tests for TripoSG, TRELLIS2, Hunyuan3D generate strategies."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

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
        ctx.get.return_value = None  # organic_reference_image not set
        ctx.dispatch_progress = AsyncMock()

        with patch.object(
            strategy, "_post_generate",
            new_callable=AsyncMock,
            return_value=(b"glb-data", "model/gltf-binary", {"vertices": "100", "faces": "200", "watertight": True}),
        ) as mock_post:
            await strategy.execute(ctx)

        # TripoSG sends empty params
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {}
        assert call_kwargs["image_b64"] is None  # no organic_reference_image in mock
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
        ctx.get.return_value = None  # organic_reference_image not set
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
        ctx.get.return_value = None  # organic_reference_image not set
        ctx.dispatch_progress = AsyncMock()

        with patch.object(
            strategy, "_post_generate",
            new_callable=AsyncMock,
            return_value=(b"glb-data", "model/gltf-binary", {}),
        ) as mock_post:
            await strategy.execute(ctx)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {"texture": False}
```

**Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_generate_strategies.py -v
```

**Step 3: 创建 TripoSG 策略**

```python
# backend/graph/strategies/generate/triposg.py
"""TripoSGGenerateStrategy — local-only via LocalModelStrategy."""

from __future__ import annotations

import logging
from typing import Any

from backend.graph.strategies.generate.base import LocalModelStrategy

logger = logging.getLogger(__name__)


class TripoSGGenerateStrategy(LocalModelStrategy):
    """TripoSG mesh generation — local HTTP endpoint only.

    Default strategy for metal 3D printing. SDF-based,
    outputs watertight mesh by design.
    """

    def check_available(self) -> bool:
        endpoint = getattr(self.config, "triposg_endpoint", None)
        if not endpoint:
            return False
        return self._check_endpoint_health(endpoint)

    async def execute(self, ctx: Any) -> None:
        endpoint = self.config.triposg_endpoint
        timeout = getattr(self.config, "timeout", 330)
        output_format = getattr(self.config, "output_format", "glb")

        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input") or {}
        image_b64 = self._get_image_b64(ctx)
        seed = gen_input.get("seed")

        await ctx.dispatch_progress(1, 3, "TripoSG 生成中")

        data, content_type, mesh_meta = await self._post_generate(
            endpoint=endpoint,
            image_b64=image_b64,
            seed=seed,
            params={},  # TripoSG: no extra params needed
            timeout=timeout,
        )

        await ctx.dispatch_progress(2, 3, "TripoSG 生成完成")

        suffix = f".{output_format}"
        output_path = self._save_output(data, ctx.job_id, suffix, "triposg")
        ctx.put_asset("raw_mesh", output_path, output_format, metadata=mesh_meta)
        await ctx.dispatch_progress(3, 3, "资产注册完成")


```

> **Note:** `_get_image_b64` 是各策略共用的辅助函数，定义在 `base.py` 的 `LocalModelStrategy` 中（见 Task 1 Step 3）。

添加 `_get_image_b64` 到 `LocalModelStrategy` 基类（在 Task 1 Step 3 的 `base.py` 中）：

```python
    @staticmethod
    def _get_image_b64(ctx: Any) -> str | None:
        """Extract reference image as base64 string for GPU server JSON API.

        Data flow:
        1. organic_reference_image (state 顶层) = file_id string (from upload)
        2. 策略通过 ctx.get("organic_reference_image") 读取 file_id
        3. 从 uploads 目录加载文件 → base64 编码
        """
        import base64 as _b64

        # 直接从管道 state 顶层读取（不在 confirmed_params 中）
        ref = ctx.get("organic_reference_image")
        if ref is None:
            return None
        if isinstance(ref, bytes):
            return _b64.b64encode(ref).decode()
        if isinstance(ref, str) and ref:
            # file_id → 从 uploads 目录加载文件
            from pathlib import Path
            uploads_dir = Path("outputs") / "organic" / "uploads"
            for ext in (".png", ".jpg", ".jpeg", ".webp"):
                candidate = uploads_dir / f"{ref}{ext}"
                if candidate.exists():
                    return _b64.b64encode(candidate.read_bytes()).decode()
            # 短字符串 = file_id 但文件缺失 → 报错（而非误当 base64）
            if len(ref) < 100:
                raise RuntimeError(f"Reference image file not found for id: {ref}")
            # 长字符串 → 假设已是 base64
            return ref
        return None
```

> **数据流说明：**
> - `organic_reference_image`（file_id）存在 state 顶层，通过 `ctx.get()` 直接访问
> - `confirmed_params` 中**不包含** reference_image（`ConfirmRequest.confirmed_params` 类型为 `dict[str, float]`）
> - 策略调用 `self._get_image_b64(ctx)` 而非传 gen_input

**Step 4: 创建 TRELLIS.2 策略**

```python
# backend/graph/strategies/generate/trellis2.py
"""TRELLIS2GenerateStrategy — local-only via LocalModelStrategy."""

from __future__ import annotations

import logging
from typing import Any

from backend.graph.strategies.generate.base import LocalModelStrategy
logger = logging.getLogger(__name__)


class TRELLIS2GenerateStrategy(LocalModelStrategy):
    """TRELLIS.2 mesh generation — local HTTP endpoint only."""

    def check_available(self) -> bool:
        endpoint = getattr(self.config, "trellis2_endpoint", None)
        if not endpoint:
            return False
        return self._check_endpoint_health(endpoint)

    async def execute(self, ctx: Any) -> None:
        endpoint = self.config.trellis2_endpoint
        timeout = getattr(self.config, "timeout", 330)
        output_format = getattr(self.config, "output_format", "glb")

        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input") or {}
        image_b64 = self._get_image_b64(ctx)
        seed = gen_input.get("seed")

        await ctx.dispatch_progress(1, 3, "TRELLIS.2 生成中")

        data, content_type, mesh_meta = await self._post_generate(
            endpoint=endpoint,
            image_b64=image_b64,
            seed=seed,
            params={"simplify": 100000, "texture": False},
            timeout=timeout,
        )

        await ctx.dispatch_progress(2, 3, "TRELLIS.2 生成完成")

        suffix = f".{output_format}"
        output_path = self._save_output(data, ctx.job_id, suffix, "trellis2")
        ctx.put_asset("raw_mesh", output_path, output_format, metadata=mesh_meta)
        await ctx.dispatch_progress(3, 3, "资产注册完成")
```

**Step 5: 重写 Hunyuan3D 策略（去 SaaS）**

```python
# backend/graph/strategies/generate/hunyuan3d.py
"""Hunyuan3DGenerateStrategy — local-only via LocalModelStrategy."""

from __future__ import annotations

import logging
from typing import Any

from backend.graph.strategies.generate.base import LocalModelStrategy
logger = logging.getLogger(__name__)


class Hunyuan3DGenerateStrategy(LocalModelStrategy):
    """Hunyuan3D mesh generation — local HTTP endpoint only.

    SaaS fallback removed. All models run on GPU server.
    """

    def check_available(self) -> bool:
        endpoint = getattr(self.config, "hunyuan3d_endpoint", None)
        if not endpoint:
            return False
        return self._check_endpoint_health(endpoint)

    async def execute(self, ctx: Any) -> None:
        endpoint = self.config.hunyuan3d_endpoint
        timeout = getattr(self.config, "timeout", 330)
        output_format = getattr(self.config, "output_format", "glb")

        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input") or {}
        image_b64 = self._get_image_b64(ctx)
        seed = gen_input.get("seed")

        await ctx.dispatch_progress(1, 3, "Hunyuan3D 生成中")

        data, content_type, mesh_meta = await self._post_generate(
            endpoint=endpoint,
            image_b64=image_b64,
            seed=seed,
            params={"texture": False},
            timeout=timeout,
        )

        await ctx.dispatch_progress(2, 3, "Hunyuan3D 生成完成")

        suffix = f".{output_format}"
        output_path = self._save_output(data, ctx.job_id, suffix, "hunyuan3d")
        ctx.put_asset("raw_mesh", output_path, output_format, metadata=mesh_meta)
        await ctx.dispatch_progress(3, 3, "资产注册完成")
```

**Step 6: 更新 `__init__.py`（删除旧策略文件推迟到 Task 4，避免 Task 3 改节点前 import 失败）**

更新 `backend/graph/strategies/generate/__init__.py`：

```python
"""3D mesh generation strategies — local GPU server endpoints."""
```

> **注意：** `tripo3d.py`、`spar3d.py`、`trellis.py` 的删除在 Task 4 执行（Task 3 先更新节点 import，
> 确保不再引用旧策略后再删除文件，避免中间态 import 失败）。

**Step 7: 运行测试，确认通过**

```bash
uv run pytest tests/test_generate_strategies.py -v
```

**Step 8: Commit**

```bash
git add -A backend/graph/strategies/generate/ tests/test_generate_strategies.py
git commit -m "feat(strategy): replace tripo3d/spar3d with triposg/trellis2, rewrite hunyuan3d to local-only"
```

---

## Task 3: 更新配置和节点注册

**目标:** 更新 `GenerateRawMeshConfig` 和 `generate_raw_mesh` 节点注册。

**Files:**
- Modify: `backend/graph/configs/generate_raw_mesh.py`
- Modify: `backend/graph/nodes/generate_raw_mesh.py`
- Test: `tests/test_generate_raw_mesh_node.py`

**Step 1: 编写测试**

```python
# tests/test_generate_raw_mesh_node.py
"""Tests for generate_raw_mesh node registration and strategy dispatch."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGenerateRawMeshConfig:

    def test_default_strategy_is_triposg(self):
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        config = GenerateRawMeshConfig()
        assert config.strategy == "triposg"

    def test_timeout_default_330(self):
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        config = GenerateRawMeshConfig()
        assert config.timeout == 330

    def test_has_three_endpoints(self):
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        config = GenerateRawMeshConfig()
        assert hasattr(config, "triposg_endpoint")
        assert hasattr(config, "trellis2_endpoint")
        assert hasattr(config, "hunyuan3d_endpoint")

    def test_no_legacy_fields(self):
        """tripo3d_api_key, spar3d_endpoint, hunyuan3d_api_key removed."""
        from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
        config = GenerateRawMeshConfig()
        assert not hasattr(config, "tripo3d_api_key")
        assert not hasattr(config, "spar3d_endpoint")
        assert not hasattr(config, "hunyuan3d_api_key")


class TestAutoStrategyMapping:

    @pytest.mark.asyncio
    async def test_auto_maps_to_triposg(self):
        """strategy='auto' should behave as 'triposg'."""
        from backend.graph.nodes.generate_raw_mesh import generate_raw_mesh_node

        ctx = MagicMock()
        ctx.config = MagicMock(strategy="auto")
        mock_strategy = AsyncMock()
        ctx.get_strategy = MagicMock(return_value=mock_strategy)

        await generate_raw_mesh_node(ctx)

        # auto should have been remapped to triposg
        assert ctx.config.strategy == "triposg"
        mock_strategy.execute.assert_awaited_once_with(ctx)

    @pytest.mark.asyncio
    async def test_invalid_strategy_raises(self):
        """Unknown strategy name raises ValueError."""
        from backend.graph.nodes.generate_raw_mesh import generate_raw_mesh_node

        ctx = MagicMock()
        ctx.config = MagicMock(strategy="nonexistent")
        # get_strategy will raise KeyError for unknown strategy
        ctx.get_strategy = MagicMock(side_effect=KeyError("nonexistent"))

        with pytest.raises((KeyError, ValueError)):
            await generate_raw_mesh_node(ctx)
```

**Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_generate_raw_mesh_node.py -v
```

**Step 3: 重写 `GenerateRawMeshConfig`**

```python
# backend/graph/configs/generate_raw_mesh.py
"""Configuration for generate_raw_mesh node."""

from __future__ import annotations

from pydantic import Field

from backend.graph.configs.base import BaseNodeConfig


class GenerateRawMeshConfig(BaseNodeConfig):
    """generate_raw_mesh node configuration.

    Supports 3 local GPU server strategies:
    - triposg (default): SDF-based, watertight, fastest
    - trellis2: SLat-based, texture support
    - hunyuan3d: Hybrid, high detail
    """

    strategy: str = "triposg"

    # TripoSG (local, :8081)
    triposg_endpoint: str | None = Field(
        default=None, json_schema_extra={"x-scope": "system"},
    )

    # TRELLIS.2 (local, :8082)
    trellis2_endpoint: str | None = Field(
        default=None, json_schema_extra={"x-scope": "system"},
    )

    # Hunyuan3D-2.1 (local, :8080)
    hunyuan3d_endpoint: str | None = Field(
        default=None, json_schema_extra={"x-scope": "system"},
    )

    # Common
    timeout: int = 330  # GPU server 300s + 30s network margin
    output_format: str = "glb"
```

**Step 4: 重写 `generate_raw_mesh` 节点**

```python
# backend/graph/nodes/generate_raw_mesh.py
"""generate_raw_mesh — strategized 3D mesh generation node.

Strategy-based node supporting 3 local GPU server models:
TripoSG (default), TRELLIS.2, Hunyuan3D-2.1.
"""

from __future__ import annotations

import logging

from backend.graph.configs.generate_raw_mesh import GenerateRawMeshConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.generate.hunyuan3d import Hunyuan3DGenerateStrategy
from backend.graph.strategies.generate.trellis2 import TRELLIS2GenerateStrategy
from backend.graph.strategies.generate.triposg import TripoSGGenerateStrategy

logger = logging.getLogger(__name__)

_STRATEGIES = {
    "triposg": TripoSGGenerateStrategy,
    "trellis2": TRELLIS2GenerateStrategy,
    "hunyuan3d": Hunyuan3DGenerateStrategy,
}


@register_node(
    name="generate_raw_mesh",
    display_name="网格生成",
    requires=["confirmed_params"],
    produces=["raw_mesh"],
    input_types=["organic"],
    config_model=GenerateRawMeshConfig,
    strategies=_STRATEGIES,
    default_strategy="triposg",
    description="通过本地 GPU 服务器 3D 生成模型创建原始网格",
)
async def generate_raw_mesh_node(ctx: NodeContext) -> None:
    """Execute 3D mesh generation via strategy dispatch.

    - "auto" -> remapped to "triposg" (default strategy)
    - Explicit strategy name -> direct dispatch
    - No fallback_chain — user explicitly chooses, failure = error
    """
    if ctx.config.strategy == "auto":
        ctx.config.strategy = "triposg"

    strategy = ctx.get_strategy()
    await strategy.execute(ctx)
```

**Step 5: 运行测试，确认通过**

```bash
uv run pytest tests/test_generate_raw_mesh_node.py tests/test_generate_strategies.py -v
```

**Step 6: Commit**

```bash
git add backend/graph/configs/generate_raw_mesh.py backend/graph/nodes/generate_raw_mesh.py tests/test_generate_raw_mesh_node.py
git commit -m "feat(node): update generate_raw_mesh to triposg/trellis2/hunyuan3d, remove fallback_chain"
```

---

## Task 4: 清理关联代码

**目标:** 删除 TripoProvider 及所有废弃引用，更新 API 端点和数据模型。

**Files:**
- Delete: `backend/infra/mesh_providers/tripo.py`
- Delete: `backend/graph/strategies/generate/trellis.py`（旧策略，已由 `trellis2.py` 替代）
- Modify: `backend/infra/mesh_providers/__init__.py` — 移除 `TripoProvider` 导出
- Modify: `backend/config.py` — 删除 `tripo3d_api_key`、`organic_default_provider` 等废弃字段；`trellis_endpoint` → `trellis2_endpoint`
- Modify: `backend/api/v1/jobs.py:487-522` — 重写 `/organic-providers` 端点，改用本地 endpoint 健康检查替代旧 Provider
- Modify: `backend/models/organic.py:67` — `provider: Literal["auto","tripo3d","hunyuan3d"]` → `Literal["auto","triposg","trellis2","hunyuan3d"]`
- Modify: `backend/models/organic_job.py:33` — 同步更新 provider 字段
- Modify: `tests/test_generate_raw_mesh.py` — 清理或重写旧测试（引用 tripo3d/spar3d/fallback_chain/hunyuan3d_api_key）
- Modify: `tests/test_mesh_providers.py` — 清理 TripoProvider 相关测试
- Check: `backend/graph/state.py` 注释中的旧 provider 引用

**Step 1: 搜索所有引用**

```bash
uv run grep -rn "tripo3d\|spar3d\|Tripo3D\|SPAR3D\|TripoProvider\|trellis_endpoint\|organic_default_provider\|hunyuan3d_api_key" backend/ tests/ --include="*.py" -l
```

**Step 2: 重写 `/organic-providers` 端点**

```python
# backend/api/v1/jobs.py — 替换 lines 487-522

@router.get("/organic-providers")
async def get_organic_providers() -> dict[str, Any]:
    """Check health of available local mesh generation endpoints."""
    from backend.config import Settings
    settings = Settings()
    if not settings.organic_enabled:
        raise APIError(
            status_code=503,
            code=ErrorCode.ORGANIC_DISABLED,
            message="Organic engine is disabled.",
        )

    # 本地端点健康检查（替代旧的 SaaS provider 检查）
    import httpx
    providers = {}
    endpoints = {
        "triposg": getattr(settings, "triposg_endpoint", None),
        "trellis2": getattr(settings, "trellis2_endpoint", None),
        "hunyuan3d": getattr(settings, "hunyuan3d_endpoint", None),
    }
    for name, endpoint in endpoints.items():
        if not endpoint:
            providers[name] = {"available": False, "configured": False}
            continue
        try:
            resp = httpx.get(f"{endpoint.rstrip('/')}/health", timeout=5)
            providers[name] = {"available": resp.status_code == 200, "configured": True}
        except Exception:
            providers[name] = {"available": False, "configured": True}

    return {"providers": providers, "default_provider": "triposg"}
```

**Step 3: 更新 OrganicGenerateRequest.provider**

```python
# backend/models/organic.py:67
provider: Literal["auto", "triposg", "trellis2", "hunyuan3d"] = "auto"
```

**Step 4: 删除废弃文件和引用**

```bash
rm backend/infra/mesh_providers/tripo.py
rm backend/graph/strategies/generate/trellis.py
```

更新 `backend/infra/mesh_providers/__init__.py`：移除 `TripoProvider` 的 import/export。

**Step 5: 清理旧测试**

- `tests/test_generate_raw_mesh.py` — 删除旧文件（已由 Task 2 的 `tests/test_generate_strategies.py` 和 Task 3 的 `tests/test_generate_raw_mesh_node.py` 替代）
- `tests/test_mesh_providers.py` — 移除 TripoProvider 相关用例

**Step 6: 运行全量测试**

```bash
uv run pytest tests/ -v
```

**Step 7: Commit**

```bash
git add -A && git commit -m "chore: clean up tripo3d/spar3d/trellis references, rewrite organic-providers endpoint"
```

---

## Task 5: 新增 shell_node 配置和策略

**目标:** 创建 ShellNodeConfig 和 MeshLibShellStrategy。

**Files:**
- Create: `backend/graph/configs/shell_node.py`
- Create: `backend/graph/strategies/shell/__init__.py`
- Create: `backend/graph/strategies/shell/meshlib_shell.py`
- Modify: `pyproject.toml` — 添加 `meshlib` 依赖
- Test: `tests/test_shell_node.py`

**Step 0: 添加 meshlib 依赖**

```bash
uv add meshlib
```

**Step 1: 编写测试**

```python
# tests/test_shell_node.py
"""Tests for shell_node — passthrough and shell modes."""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestShellNodeConfig:

    def test_defaults(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        config = ShellNodeConfig()
        assert config.shell_enabled is False
        assert config.wall_thickness == 2.0
        assert config.voxel_resolution == 0  # adaptive
        assert config.strategy == "meshlib"

    def test_wall_thickness_must_be_positive(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        with pytest.raises(Exception):  # ValidationError
            ShellNodeConfig(wall_thickness=0)

    def test_wall_thickness_max_50(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        with pytest.raises(Exception):
            ShellNodeConfig(wall_thickness=51)


class TestShellNodePassthrough:

    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self):
        """shell_enabled=False -> scaled_mesh passed through as shelled_mesh."""
        from backend.graph.nodes.shell_node import shell_node_fn

        ctx = MagicMock()
        ctx.config = MagicMock(shell_enabled=False)
        mock_asset = MagicMock(path="/tmp/scaled.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.has_asset.return_value = True

        await shell_node_fn(ctx)

        ctx.put_asset.assert_called_once()
        call_args = ctx.put_asset.call_args
        assert call_args[0][0] == "shelled_mesh"  # asset key
        assert call_args[0][1] == "/tmp/scaled.glb"  # same path = passthrough


class TestShellNodeFailure:

    @pytest.mark.asyncio
    async def test_failure_raises_not_silent(self):
        """non_fatal=False -> shell failure raises exception."""
        from backend.graph.strategies.shell.meshlib_shell import MeshLibShellStrategy

        strategy = MeshLibShellStrategy(
            config=MagicMock(wall_thickness=2.0, voxel_resolution=256)
        )
        ctx = MagicMock()
        ctx.job_id = "test"
        mock_asset = MagicMock(path="/tmp/nonexistent.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.dispatch_progress = AsyncMock()

        with pytest.raises(Exception):
            await strategy.execute(ctx)


class TestAdaptiveResolution:

    def test_resolution_formula(self):
        """Verify adaptive resolution: min(512, max(256, ceil(bbox_max / wall_thickness * 5)))."""
        from backend.graph.strategies.shell.meshlib_shell import _compute_adaptive_resolution

        # Small object: 50mm bbox, 2mm wall -> ceil(50/2*5) = 125 -> clamped to 256
        assert _compute_adaptive_resolution(50.0, 2.0) == 256

        # Medium: 200mm bbox, 2mm wall -> ceil(200/2*5) = 500 -> 500
        assert _compute_adaptive_resolution(200.0, 2.0) == 500

        # Large: 500mm bbox, 1mm wall -> ceil(500/1*5) = 2500 -> clamped to 512
        assert _compute_adaptive_resolution(500.0, 1.0) == 512
```

**Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_shell_node.py -v
```

**Step 3: 创建 ShellNodeConfig**

```python
# backend/graph/configs/shell_node.py
"""Configuration for shell_node."""

from __future__ import annotations

from pydantic import Field

from backend.graph.configs.base import BaseNodeConfig


class ShellNodeConfig(BaseNodeConfig):
    """shell_node configuration — SDF offset shelling."""

    strategy: str = "meshlib"
    wall_thickness: float = Field(2.0, gt=0, le=50.0)  # mm
    voxel_resolution: int = 0  # 0 = adaptive (min 256, max 512)
    shell_enabled: bool = False  # default off, user explicitly enables
```

**Step 4: 创建 MeshLibShellStrategy**

```python
# backend/graph/strategies/shell/__init__.py
"""Shell strategies for hollow mesh generation."""

# backend/graph/strategies/shell/meshlib_shell.py
"""MeshLibShellStrategy — SDF offset shelling via MeshLib."""

from __future__ import annotations

import asyncio
import logging
import math
import tempfile
from pathlib import Path
from typing import Any

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)


def _compute_adaptive_resolution(bbox_max: float, wall_thickness: float) -> int:
    """Compute adaptive voxel resolution.

    Formula: min(512, max(256, ceil(bbox_max / wall_thickness * 5)))
    Ensures >= 5 voxels across wall thickness, capped at 512 to prevent OOM.
    """
    raw = math.ceil(bbox_max / wall_thickness * 5)
    return min(512, max(256, raw))


class MeshLibShellStrategy(NodeStrategy):
    """SDF offset shelling using MeshLib boolean operations."""

    async def execute(self, ctx: Any) -> None:
        """Execute SDF-based mesh shelling."""
        config = ctx.config
        wall_thickness = config.wall_thickness
        voxel_resolution = config.voxel_resolution

        asset = ctx.get_asset("scaled_mesh")
        await ctx.dispatch_progress(1, 5, "加载网格")

        result_path, actual_resolution = await asyncio.to_thread(
            self._shell_sync,
            asset.path,
            wall_thickness,
            voxel_resolution,
            ctx.job_id,
        )

        ctx.put_asset(
            "shelled_mesh", result_path, "mesh",
            metadata={
                "wall_thickness": wall_thickness,
                "voxel_resolution": actual_resolution,  # 记录实际使用的分辨率（非原始配置值 0）
                "shelled": True,
            },
        )
        await ctx.dispatch_progress(5, 5, "抽壳完成")

    @staticmethod
    def _shell_sync(
        mesh_path: str,
        wall_thickness: float,
        voxel_resolution: int,
        job_id: str,
    ) -> tuple[str, int]:
        """Synchronous shelling — runs in thread. Returns (path, actual_resolution)."""
        import trimesh

        mesh = trimesh.load(mesh_path, force="mesh")

        # Compute adaptive resolution if needed
        if voxel_resolution <= 0:
            bbox_max = float(max(mesh.bounding_box.extents))
            voxel_resolution = _compute_adaptive_resolution(bbox_max, wall_thickness)
            logger.info("shell_node: adaptive resolution = %d", voxel_resolution)

        try:
            import meshlib.mrmeshpy as mr

            # 1. Convert trimesh -> MeshLib
            mr_mesh = _trimesh_to_meshlib(mesh)

            # 2. Compute SDF volume
            voxel_size = float(max(mesh.bounding_box.extents)) / voxel_resolution
            params = mr.MeshToVolumeParams()
            params.surfaceOffset = voxel_size * 3
            params.voxelSize = voxel_size
            volume = mr.meshToVolume(mr_mesh, params)

            # 3. Extract inner wall at offset = -wall_thickness
            inner_params = mr.VolumeToMeshByDualMarchingCubesParams()
            inner_params.iso = -wall_thickness
            inner_mesh = mr.volumeToMeshByDualMarchingCubes(volume, inner_params)

            # 4. Boolean difference: outer - inner = hollow shell
            result = mr.boolean(mr_mesh, inner_mesh, mr.BooleanOperation.DifferenceAB)

            # 5. Convert back to trimesh and verify
            result_trimesh = _meshlib_to_trimesh(result.mesh, trimesh)

            if not result_trimesh.is_watertight:
                raise RuntimeError(
                    "shell_node: 抽壳结果非水密（non-watertight），"
                    "后续布尔操作将失败。请调整 voxel_resolution 或 wall_thickness。"
                )

            # 使用绝对值比较（防止反向法线 mesh 的 volume 为负数误判）
            original_vol = abs(mesh.volume) if mesh.volume != 0 else 1e-10
            result_vol = abs(result_trimesh.volume)
            volume_ratio = result_vol / original_vol
            if volume_ratio < 0.05:
                raise RuntimeError(
                    f"Shell result volume is only {volume_ratio:.1%} of original — "
                    "likely boolean operation failure. Try increasing voxel_resolution."
                )

            # 6. Export
            output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "shell"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(output_dir / f"{job_id}_shelled.glb")
            result_trimesh.export(output_path)
            return output_path, voxel_resolution

        except ImportError:
            raise RuntimeError(
                "meshlib not installed. Install with: pip install meshlib"
            )


def _trimesh_to_meshlib(mesh):
    """Convert trimesh.Trimesh to meshlib mr.Mesh.

    必须使用 meshlib.mrmeshnumpy 桥接模块，mrmeshpy.meshFromFacesVerts
    不接受 NumPy 数组（需要 C++ vector 类型）。
    """
    import numpy as np
    import meshlib.mrmeshnumpy as mrmeshnumpy
    verts = np.array(mesh.vertices, dtype=np.float32)
    faces = np.array(mesh.faces, dtype=np.int32)
    return mrmeshnumpy.meshFromFacesVerts(faces, verts)


def _meshlib_to_trimesh(mr_mesh, trimesh_mod):
    """Convert meshlib mr.Mesh to trimesh.Trimesh."""
    import meshlib.mrmeshnumpy as mrmeshnumpy
    verts = mrmeshnumpy.getNumpyVerts(mr_mesh)
    faces = mrmeshnumpy.getNumpyFaces(mr_mesh.topology)
    return trimesh_mod.Trimesh(vertices=verts, faces=faces)
```

**Step 5: 运行测试**

```bash
uv run pytest tests/test_shell_node.py -v
```

**Step 6: Commit**

```bash
git add backend/graph/configs/shell_node.py backend/graph/strategies/shell/ tests/test_shell_node.py
git commit -m "feat: add shell_node config and MeshLibShellStrategy"
```

---

## Task 6: 注册 shell_node + 更新 boolean_assemble

**目标:** 创建 shell_node 节点文件，更新 boolean_assemble 读取 `shelled_mesh`。

**Files:**
- Create: `backend/graph/nodes/shell_node.py`
- Modify: `backend/graph/nodes/boolean_assemble.py` (lines 30, 49, 78)
- Modify: `backend/graph/strategies/boolean/manifold3d.py` (line 43)
- Test: `tests/test_shell_boolean_integration.py`

**Step 1: 编写测试**

```python
# tests/test_shell_boolean_integration.py
"""Integration tests: shell_node passthrough + boolean_assemble compatibility."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestBooleanAssembleReadsShelled:

    def test_boolean_assemble_requires_shelled_mesh(self):
        """After update, boolean_assemble requires shelled_mesh."""
        from backend.graph.registry import NodeRegistry
        registry = NodeRegistry()
        # Import to trigger registration
        import backend.graph.nodes.boolean_assemble  # noqa: F401
        desc = registry.get("boolean_assemble")
        assert "shelled_mesh" in desc.requires

    @pytest.mark.asyncio
    async def test_passthrough_no_cuts_reads_shelled(self):
        """Passthrough path reads shelled_mesh (not scaled_mesh)."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = MagicMock()
        ctx.config = MagicMock(strategy="manifold3d")
        ctx.has_asset.side_effect = lambda k: k == "shelled_mesh"
        mock_asset = MagicMock(path="/tmp/shelled.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.get_data.return_value = None  # no organic_spec -> no cuts -> passthrough

        await boolean_assemble_node(ctx)

        ctx.get_asset.assert_called_with("shelled_mesh")
        ctx.put_asset.assert_called_once()
        assert ctx.put_asset.call_args[0][0] == "final_mesh"
```

**Step 2: 运行测试，确认失败**

```bash
uv run pytest tests/test_shell_boolean_integration.py -v
```

**Step 3: 创建 shell_node 节点**

```python
# backend/graph/nodes/shell_node.py
"""shell_node — SDF offset shelling for hollow thin-wall structures.

Passthrough when shell_enabled=False: scaled_mesh -> shelled_mesh (zero cost).
When enabled: MeshLib SDF offset creates hollow body with specified wall thickness.
"""

from __future__ import annotations

import logging

from backend.graph.configs.shell_node import ShellNodeConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.shell.meshlib_shell import MeshLibShellStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="shell_node",
    display_name="抽壳",
    requires=["scaled_mesh"],
    produces=["shelled_mesh"],
    input_types=["organic"],
    config_model=ShellNodeConfig,
    strategies={"meshlib": MeshLibShellStrategy},
    default_strategy="meshlib",
    non_fatal=False,
    description="SDF 偏移抽壳，将实心 mesh 转为指定壁厚的中空薄壁体",
)
async def shell_node_fn(ctx: NodeContext) -> None:
    """Execute mesh shelling or passthrough.

    Passthrough conditions:
    - shell_enabled=False -> copy scaled_mesh as shelled_mesh
    - No scaled_mesh -> skip

    Failure behavior:
    - non_fatal=False -> shell failure raises, pipeline stops
    """
    if not ctx.has_asset("scaled_mesh"):
        logger.warning("shell_node: no scaled_mesh asset, skipping")
        ctx.put_data("shell_node_status", "skipped_no_input")
        return

    if not ctx.config.shell_enabled:
        # Passthrough: zero-cost copy
        scaled = ctx.get_asset("scaled_mesh")
        ctx.put_asset(
            "shelled_mesh", scaled.path, "mesh",
            metadata={"passthrough": True, "shelled": False},
        )
        ctx.put_data("shell_node_status", "passthrough")
        logger.info("shell_node: shell_enabled=False, passthrough")
        return

    # Dispatch to strategy (MeshLib SDF offset)
    strategy = ctx.get_strategy()
    await strategy.execute(ctx)
    ctx.put_data("shell_node_status", "completed")
```

**Step 4: 更新 boolean_assemble**

在 `backend/graph/nodes/boolean_assemble.py` 中：
- Line 30: `requires=["scaled_mesh"]` → `requires=["shelled_mesh"]`
- Line 49: `ctx.has_asset("scaled_mesh")` → `ctx.has_asset("shelled_mesh")`
- Line 78: `ctx.get_asset("scaled_mesh")` → `ctx.get_asset("shelled_mesh")`
- Lines 1-6: 更新 docstring 中 `scaled_mesh` 引用

在 `backend/graph/strategies/boolean/manifold3d.py` 中：
- Line 43: `ctx.get_asset("scaled_mesh")` → `ctx.get_asset("shelled_mesh")`

**Step 4.1: 更新旧测试中的 `scaled_mesh` 引用**

以下测试文件引用了 `boolean_assemble` 的 `scaled_mesh`，需同步更新为 `shelled_mesh`：
- `tests/test_boolean_assemble.py` — mock 资产从 `scaled_mesh` 改为 `shelled_mesh`
- `tests/test_phase2_integration.py` — `boolean_assemble` 相关断言更新
- `tests/test_mesh_pipeline.py` — `scaled_mesh` → `shelled_mesh` 引用更新

```bash
uv run grep -rn "scaled_mesh" tests/ --include="*.py"
```

逐个文件更新所有 `boolean_assemble` 上下文中的 `scaled_mesh` → `shelled_mesh`。

**Step 5: 运行测试**

```bash
uv run pytest tests/test_shell_node.py tests/test_shell_boolean_integration.py -v
```

**Step 6: 运行全量测试确认无回归**

```bash
uv run pytest tests/ -v
```

**Step 7: Commit**

```bash
git add backend/graph/nodes/shell_node.py backend/graph/nodes/boolean_assemble.py backend/graph/strategies/boolean/manifold3d.py tests/test_shell_boolean_integration.py
git commit -m "feat: add shell_node + update boolean_assemble to read shelled_mesh"
```

---

## Task 7: 全量回归测试 + 最终验证

**目标:** 确保所有变更通过测试，管道拓扑正确。

**Step 1: 运行完整测试套件**

```bash
uv run pytest tests/ -v --tb=short
```

**Step 2: 验证管道拓扑**

```python
# 在 Python REPL 中验证
from backend.graph.discovery import discover_nodes
from backend.graph.registry import NodeRegistry

discover_nodes()
registry = NodeRegistry()

# 验证有机管道节点链
organic_nodes = [n for n in registry.all() if "organic" in n.input_types]
for n in organic_nodes:
    print(f"{n.name}: requires={n.requires} produces={n.produces}")

# 验证 shell_node 在 mesh_scale 和 boolean_assemble 之间
shell = registry.get("shell_node")
assert "scaled_mesh" in shell.requires
assert "shelled_mesh" in shell.produces

boolean = registry.get("boolean_assemble")
assert "shelled_mesh" in boolean.requires
```

**Step 3: 验证 generate_raw_mesh 策略注册**

```python
gen = registry.get("generate_raw_mesh")
assert set(gen.strategies.keys()) == {"triposg", "trellis2", "hunyuan3d"}
assert gen.default_strategy == "triposg"
assert gen.fallback_chain == []  # no fallback
```

**Step 4: TypeScript 前端检查（如有涉及）**

```bash
cd frontend && npx tsc --noEmit
```

**Step 5: Commit 最终状态**

```bash
git add -A && git commit -m "test: verify pipeline topology and full regression suite"
```
