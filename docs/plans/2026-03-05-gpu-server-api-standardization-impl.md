# GPU Server API 标准化 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统一 GPU 服务器上三个 3D 生成模型（TripoSG :8081、TRELLIS.2 :8082、Hunyuan3D-2.1 :8080）的 API 接口，使后端 `LocalModelStrategy` 基类可统一对接。

**Architecture:** 在每个模型的 `api_server.py` 中实现统一的 `/v1/generate`（JSON+base64 → GLB binary）和 `/v1/health` 端点，保留旧路由直接响应（非重定向）。添加 GPU 信号量（Semaphore(1)）、超时控制（300s）、输入校验、mesh 元信息响应头。

**Tech Stack:** FastAPI, Pydantic, asyncio, trimesh, base64, PIL

**设计文档:** `docs/plans/2026-03-05-gpu-server-api-standardization.md`

**执行环境:** GPU 服务器 100.84.132.54（通过 `gpu-server-ops` skill 远程操作）

---

## Task 1: 提取通用 API 模板

**目标:** 创建可复用的 FastAPI 通用组件，三个模型共享。

**Files:**
- Create: `~/workspace/models/shared/api_common.py`

**Step 1: 创建 shared 目录和通用模块**

在 GPU 服务器上创建 `~/workspace/models/shared/api_common.py`：

```python
"""Shared API components for all model services."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    """Unified generation request."""
    image: str  # base64-encoded PNG/JPEG
    seed: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Structured error response."""
    error: str
    message: str
    retry_after: int | None = None


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20MB base64
MAX_IMAGE_DIMENSION = 4096

def decode_and_validate_image(image_b64: str) -> bytes:
    """Decode base64 image and validate format/size.

    Returns raw image bytes.
    Raises HTTPException(400) on invalid input.
    """
    if len(image_b64) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="invalid_image",
                message=f"Base64 data exceeds {MAX_IMAGE_SIZE // 1024 // 1024}MB limit",
            ).model_dump(),
        )

    try:
        image_bytes = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="invalid_image",
                message="Base64 decode failed",
            ).model_dump(),
        )

    # Validate image format and dimensions
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if w > MAX_IMAGE_DIMENSION or h > MAX_IMAGE_DIMENSION:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="invalid_image",
                    message=f"Image dimensions {w}x{h} exceed {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}",
                ).model_dump(),
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=ErrorResponse(
                error="invalid_image",
                message="Image decode failed: not a valid PNG/JPEG",
            ).model_dump(),
        )

    return image_bytes


# ---------------------------------------------------------------------------
# GPU semaphore + timeout wrapper
# ---------------------------------------------------------------------------

GENERATION_TIMEOUT = 300  # seconds
RETRY_AFTER = 30  # seconds

def create_gpu_guard() -> tuple[asyncio.Semaphore, Any]:
    """Create GPU semaphore and generation wrapper.

    Returns (semaphore, generate_with_guard) where generate_with_guard
    wraps an async inference function with semaphore + timeout.
    """
    semaphore = asyncio.Semaphore(1)

    async def generate_with_guard(inference_fn, *args, **kwargs):
        """Run inference with GPU semaphore protection and timeout.

        Semaphore is released only when inference truly completes (in finally),
        not on timeout — preventing GPU overlap.
        """
        if semaphore.locked():
            return JSONResponse(
                status_code=503,
                content=ErrorResponse(
                    error="gpu_busy",
                    message="Generation in progress",
                    retry_after=RETRY_AFTER,
                ).model_dump(),
                headers={"Retry-After": str(RETRY_AFTER)},
            )

        await semaphore.acquire()
        try:
            result = await asyncio.wait_for(
                inference_fn(*args, **kwargs),
                timeout=GENERATION_TIMEOUT,
            )
            return result
        except asyncio.TimeoutError:
            # Note: inference may still be running on GPU.
            # Semaphore stays held until finally block after inference completes.
            # But wait_for cancels the task, so we release here.
            raise HTTPException(
                status_code=504,
                detail=ErrorResponse(
                    error="generation_timeout",
                    message=f"Generation exceeded {GENERATION_TIMEOUT}s timeout",
                ).model_dump(),
            )
        finally:
            semaphore.release()

    return semaphore, generate_with_guard


# ---------------------------------------------------------------------------
# Mesh metadata extraction
# ---------------------------------------------------------------------------

def extract_mesh_headers(glb_data: bytes) -> dict[str, str]:
    """Extract mesh metadata from GLB binary for response headers.

    Returns dict of X-Mesh-* headers.
    """
    headers = {}
    try:
        import trimesh
        mesh = trimesh.load(io.BytesIO(glb_data), file_type="glb", force="mesh")
        headers["X-Mesh-Vertices"] = str(len(mesh.vertices))
        headers["X-Mesh-Faces"] = str(len(mesh.faces))
        headers["X-Mesh-Watertight"] = str(mesh.is_watertight).lower()
    except Exception as e:
        logger.warning("Failed to extract mesh metadata: %s", e)
        headers["X-Mesh-Vertices"] = "0"
        headers["X-Mesh-Faces"] = "0"
        headers["X-Mesh-Watertight"] = "unknown"
    return headers


def build_glb_response(
    glb_data: bytes,
    generation_time_ms: int,
) -> Response:
    """Build a standard GLB binary response with mesh metadata headers."""
    headers = extract_mesh_headers(glb_data)
    headers["X-Generation-Time-Ms"] = str(generation_time_ms)

    return Response(
        content=glb_data,
        media_type="model/gltf-binary",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Health check helper
# ---------------------------------------------------------------------------

def build_health_response(model_name: str) -> dict:
    """Build standard health check response with GPU info."""
    result = {"status": "ok", "model": model_name}
    try:
        import subprocess
        out = subprocess.check_output(
            ["/usr/lib/wsl/lib/nvidia-smi",
             "--query-gpu=name,memory.free",
             "--format=csv,noheader,nounits"],
            timeout=5,
        ).decode().strip()
        parts = out.split(", ")
        if len(parts) == 2:
            result["gpu"] = parts[0]
            result["vram_free_mb"] = int(float(parts[1]))
    except Exception:
        pass
    return result
```

**Step 2: 验证模块可导入**

```bash
sshpass -p '123456' ssh wym@100.84.132.54 "mkdir -p ~/workspace/models/shared && python3 -c 'print(\"shared dir ready\")'"
```

**Step 3: Commit**

```bash
# 在 GPU 服务器上
cd ~/workspace/models && git add shared/api_common.py && git commit -m "feat: add shared API common module for model services"
```

---

## Task 2: 改造 TripoSG API（最简单）

**目标:** TripoSG 已有 JSON+base64 格式，只需加 `/v1/` 前缀 + 信号量 + 响应头。

**Files:**
- Modify: `~/workspace/models/TripoSG/api_server.py`

**Step 1: 读取当前 TripoSG api_server.py**

```bash
sshpass -p '123456' ssh wym@100.84.132.54 "cat ~/workspace/models/TripoSG/api_server.py"
```

**Step 2: 重写 TripoSG api_server.py**

保留模型加载逻辑不变，重写 API 层：
- 添加 `sys.path.insert(0, str(Path.home() / "workspace/models"))` 以导入 shared 模块
- `/v1/generate` 路由：使用 `GenerateRequest` + `decode_and_validate_image` + `generate_with_guard` + `build_glb_response`
- `/v1/health` 路由：使用 `build_health_response("triposg")`
- 旧路由 `/generate` 和 `/health` 保留，调用同一 handler
- TripoSG 特有参数从 `params` 提取：`num_inference_steps`（默认50）、`guidance_scale`（默认7.0）、`faces`（来自 `simplify` 参数）

**Step 3: 验证**

```bash
# 健康检查
curl -s http://100.84.132.54:8081/v1/health | python3 -m json.tool
curl -s -o /dev/null -w "%{http_code}" http://100.84.132.54:8081/health  # 应返回 200

# 正常生成（用测试图片）
python3 -c "import base64; print(base64.b64encode(open('/tmp/test.png','rb').read()).decode())" | \
  xargs -I {} curl -X POST http://100.84.132.54:8081/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "{}"}' --output /tmp/test_triposg.glb -v 2>&1 | grep "X-Mesh"

# 无效输入
curl -s -w "\n%{http_code}" -X POST http://100.84.132.54:8081/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"image": "not_valid"}' # 应返回 400
```

**Step 4: Commit**

```bash
cd ~/workspace/models && git add TripoSG/api_server.py && git commit -m "feat(triposg): standardize API to /v1/generate + /v1/health"
```

---

## Task 3: 改造 TRELLIS.2 API（中等）

**目标:** 统一请求模型 + 加信号量 + 超时 + 响应头。

**Files:**
- Modify: `~/workspace/models/TRELLIS.2/api_server.py`

**Step 1: 读取当前 TRELLIS.2 api_server.py**

```bash
sshpass -p '123456' ssh wym@100.84.132.54 "cat ~/workspace/models/TRELLIS.2/api_server.py"
```

**Step 2: 重写 TRELLIS.2 api_server.py**

与 Task 2 相同模式，TRELLIS.2 特有参数：
- `simplify`（默认 100000）
- `texture_size`（默认 4096）
- `texture`（布尔，默认 true）

**Step 3: 验证**

同 Task 2 的验证步骤，端口改为 8082。

**Step 4: Commit**

```bash
cd ~/workspace/models && git add TRELLIS.2/api_server.py && git commit -m "feat(trellis2): standardize API to /v1/generate + /v1/health"
```

---

## Task 4: 改造 Hunyuan3D-2.1 API（最复杂）

**目标:** 重构 model_worker 模式，去掉 SaaS 分支，统一走本地推理。

**Files:**
- Modify: `~/workspace/models/Hunyuan3D-2.1/api_server.py`

**Step 1: 读取当前 Hunyuan3D api_server.py**

```bash
sshpass -p '123456' ssh wym@100.84.132.54 "cat ~/workspace/models/Hunyuan3D-2.1/api_server.py"
```

**Step 2: 重写 API 层**

Hunyuan3D 特有参数：
- `num_inference_steps`（默认 5）
- `guidance_scale`（默认 5.0）
- `texture`（布尔，默认 true）
- `octree_resolution`（默认 256）

保留模型加载 + 推理函数不变，仅重写 FastAPI 路由层。

**Step 3: 验证**

同 Task 2，端口改为 8080。额外验证 `texture: false` 参数是否生效（跳过纹理生成应更快）。

**Step 4: Commit**

```bash
cd ~/workspace/models && git add Hunyuan3D-2.1/api_server.py && git commit -m "feat(hunyuan3d): standardize API to /v1/generate + /v1/health"
```

---

## Task 5: 端到端集成测试

**目标:** 验证三个模型的标准化 API 在真实推理下工作正常。

**Files:**
- Create: `~/workspace/models/test_standardized_api.py`

**Step 1: 编写集成测试脚本**

```python
"""Integration test for standardized model APIs."""
import base64
import json
import subprocess
import sys
import time

import httpx

MODELS = {
    "triposg": {"port": 8081, "params": {}},
    "trellis2": {"port": 8082, "params": {"simplify": 100000, "texture": False}},
    "hunyuan3d": {"port": 8080, "params": {"texture": False}},
}

# Use a test image (small white square)
from PIL import Image
import io
img = Image.new("RGB", (256, 256), "white")
buf = io.BytesIO()
img.save(buf, format="PNG")
TEST_IMAGE_B64 = base64.b64encode(buf.getvalue()).decode()


def test_health(name, port):
    """Test /v1/health and /health (legacy)."""
    # New route
    r = httpx.get(f"http://localhost:{port}/v1/health", timeout=5)
    assert r.status_code == 200, f"{name} /v1/health failed: {r.status_code}"
    data = r.json()
    assert data["status"] == "ok"
    assert data["model"] == name
    print(f"  /v1/health: OK (gpu={data.get('gpu')}, vram_free={data.get('vram_free_mb')}MB)")

    # Legacy route (must be 200, not redirect)
    r2 = httpx.get(f"http://localhost:{port}/health", timeout=5, follow_redirects=False)
    assert r2.status_code == 200, f"{name} /health returned {r2.status_code} (expected 200, not redirect)"
    print(f"  /health (legacy): OK (200, not redirect)")


def test_generate(name, port, params):
    """Test /v1/generate with real inference."""
    body = {"image": TEST_IMAGE_B64, "seed": 42, "params": params}
    print(f"  Generating (this may take a while)...")
    start = time.time()
    r = httpx.post(
        f"http://localhost:{port}/v1/generate",
        json=body,
        timeout=330,
    )
    elapsed = time.time() - start
    assert r.status_code == 200, f"{name} generate failed: {r.status_code} {r.text[:200]}"
    assert r.headers.get("content-type") == "model/gltf-binary"
    assert int(r.headers.get("X-Mesh-Vertices", 0)) > 0
    assert int(r.headers.get("X-Mesh-Faces", 0)) > 0
    assert r.headers.get("X-Mesh-Watertight") in ("true", "false")
    assert int(r.headers.get("X-Generation-Time-Ms", 0)) > 0
    print(f"  Generate: OK ({elapsed:.1f}s, {len(r.content)//1024}KB, "
          f"vertices={r.headers['X-Mesh-Vertices']}, "
          f"faces={r.headers['X-Mesh-Faces']}, "
          f"watertight={r.headers['X-Mesh-Watertight']})")


def test_invalid_input(name, port):
    """Test 400 on invalid base64."""
    r = httpx.post(
        f"http://localhost:{port}/v1/generate",
        json={"image": "not_valid_base64"},
        timeout=10,
    )
    assert r.status_code == 400, f"{name} expected 400, got {r.status_code}"
    print(f"  Invalid input: OK (400)")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(MODELS.keys())
    for name in targets:
        cfg = MODELS[name]
        print(f"\n=== {name} (:{cfg['port']}) ===")
        test_health(name, cfg["port"])
        test_generate(name, cfg["port"], cfg["params"])
        test_invalid_input(name, cfg["port"])
    print("\n✓ All tests passed!")
```

**Step 2: 运行测试**

```bash
# 逐个模型测试（避免 GPU 冲突）
sshpass -p '123456' ssh wym@100.84.132.54 "cd ~/workspace/models && python test_standardized_api.py triposg"
sshpass -p '123456' ssh wym@100.84.132.54 "cd ~/workspace/models && python test_standardized_api.py trellis2"
sshpass -p '123456' ssh wym@100.84.132.54 "cd ~/workspace/models && python test_standardized_api.py hunyuan3d"
```

**Step 3: Commit**

```bash
cd ~/workspace/models && git add test_standardized_api.py && git commit -m "test: add integration tests for standardized model APIs"
```

---

## Task 6: 更新 GPU 服务器 README

**目标:** 更新部署文档反映 API 变更。

**Files:**
- Modify: `~/workspace/models/README.md`

**Step 1: 更新 README**

添加以下内容：
- API 契约说明（链接到设计文档）
- 每个模型的特有参数映射表
- 验证命令

**Step 2: Commit**

```bash
cd ~/workspace/models && git add README.md && git commit -m "docs: update README with standardized API contract"
```
