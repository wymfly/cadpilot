# Organic LangGraph Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将创意雕塑(organic)管道从独立 FastAPI 编排迁移到统一 LangGraph StateGraph，使 text/drawing/organic 三种 input_type 共享同一生命周期管理。

**Architecture:** Organic 作为 CadJobState 图的第三条路径嵌入。3 个新节点（analyze_organic → generate_organic_mesh → postprocess_organic）替换 stub_organic，共用 create_job/confirm_with_user/finalize 节点。前端统一调用 `/api/v1/jobs`，删除 `/api/v1/organic`。

**Tech Stack:** LangGraph StateGraph, FastAPI, Pydantic v2, trimesh, pymeshlab, manifold3d, React/TypeScript

**Design docs:** `openspec/changes/organic-langgraph-migration/`, `docs/plans/2026-03-01-organic-langgraph-migration-design.md`

---

## 执行结构

```
Phase 0 (串行) ─ 接口定义：Task 1 (state + API)
    ↓
Phase 1 (并行) ─ 模块实现：
    Agent A: Task 2 (organic 节点) — nodes/organic.py (新文件)
    Agent B: Task 3 (finalize 扩展) — nodes/lifecycle.py
    ↓
Phase 2 (串行) ─ 图拓扑组装：Task 4 — builder.py + routing.py + analysis.py 清理
    ↓
Phase 3 (串行) ─ 单元测试：Task 5 — tests/
    ↓
Phase 4 (并行) ─ 清理+前端：
    Agent C: Task 6 (后端清理) — organic.py 删除 + router.py + jobs.py 端点迁移
    Agent D: Task 7 (前端改造) — frontend/src/
    ↓
Phase 5 (串行) ─ 集成验证：Task 8
```

### 文件独立性矩阵

| | state.py | jobs.py | organic.py(新) | lifecycle.py | builder.py | routing.py | analysis.py | organic.py(旧) | router.py | frontend/ |
|--|--|--|--|--|--|--|--|--|--|--|
| **Task 1** | ✏️ | ✏️ | | | | | | | | |
| **Task 2** | | | ✏️ | | | | | | | |
| **Task 3** | | | | ✏️ | | | | | | |
| **Task 4** | | | | | ✏️ | ✏️ | ✏️ | | | |
| **Task 6** | | ✏️ | | | | | | 🗑️ | ✏️ | |
| **Task 7** | | | | | | | | | | ✏️ |

Phase 1 (Task 2 || Task 3) 无文件交叉 ✓
Phase 4 (Task 6 || Task 7) 无文件交叉 ✓

---

## Task 1: CadJobState 扩展 + API 请求模型 `[backend]`

**Phase 0 — 串行（接口定义，所有后续任务依赖此任务）**

**Skill:** `@sqlalchemy-orm`, `@streaming-api-patterns`

**Files:**
- Modify: `backend/graph/state.py:1-43`
- Modify: `backend/api/v1/jobs.py:170-205` (CreateJobRequest)
- Modify: `backend/api/v1/jobs.py:367-442` (confirm_job_endpoint)
- Test: `uv run pytest tests/ -v -k "not organic"` (回归)

### Step 1: 扩展 CadJobState

修改 `backend/graph/state.py`，在 `# ── Generation outputs ──` 之后添加 organic 字段：

```python
"""CadJobState — the single state object flowing through the CAD Job StateGraph."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CadJobState(TypedDict, total=False):
    # ── Input ──
    job_id: str
    input_type: str              # "text" | "drawing" | "organic"
    input_text: str | None
    image_path: str | None

    # ── Analysis outputs ──
    intent: dict | None          # IntentSpec.model_dump()
    matched_template: str | None
    drawing_spec: dict | None    # DrawingSpec.model_dump()

    # ── HITL confirmation inputs ──
    confirmed_params: dict | None
    confirmed_spec: dict | None
    disclaimer_accepted: bool

    # ── Generation outputs ──
    step_path: str | None
    model_url: str | None        # GLB preview URL
    printability: dict | None

    # ── Organic outputs ──
    organic_spec: dict | None            # OrganicSpec.model_dump()
    organic_provider: str | None         # "auto" | "tripo3d" | "hunyuan3d"
    organic_quality_mode: str | None     # "draft" | "standard" | "high"
    organic_reference_image: str | None  # uploaded file_id
    organic_constraints: dict | None     # {bounding_box, engineering_cuts}
    raw_mesh_path: str | None
    mesh_stats: dict | None
    organic_warnings: Annotated[list[str], operator.add]
    organic_result: dict | None          # {model_url, stl_url, threemf_url, ...}

    # ── Status & error ──
    status: str                  # mirrors JobStatus value
    error: str | None
    failure_reason: str | None   # typed: timeout | rate_limited | invalid_json | generation_error


# Maps CadJobState field names → ORM JobModel column names where they differ.
STATE_TO_ORM_MAPPING: dict[str, str] = {
    "confirmed_spec": "drawing_spec_confirmed",
    "printability": "printability_result",
    # step_path and model_url are assembled into the ORM `result` JSON column
    # by finalize_node — no direct 1:1 mapping needed here.
    # organic_spec is saved to DB directly in analyze_organic_node,
    # organic_result is assembled into `result` JSON column by finalize_node.
}
```

### Step 2: 运行回归测试确认无破坏

Run: `uv run pytest tests/ -v -k "not organic_api"`
Expected: 全部通过（新增字段 total=False 不影响现有路径）

### Step 3: 扩展 CreateJobRequest

修改 `backend/api/v1/jobs.py`，在 `CreateJobRequest` 中添加 organic 字段：

```python
class CreateJobRequest(BaseModel):
    input_type: str = "text"
    text: str = ""
    prompt: str = ""
    provider: str = "auto"
    quality_mode: str = "standard"
    reference_image: str | None = None                  # organic: uploaded file_id
    constraints: dict[str, Any] | None = None           # organic: {bounding_box, engineering_cuts}
    pipeline_config: dict[str, Any] = Field(default_factory=dict)
```

在 `create_job_endpoint` 中添加 organic 校验和初始 state 映射：

```python
# 在 initial_state 构建后，添加 organic 字段映射
if body.input_type == "organic":
    if not (body.text or body.prompt or body.reference_image):
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message="Organic mode requires at least one of prompt or reference_image.",
        )
    initial_state["organic_provider"] = body.provider
    initial_state["organic_quality_mode"] = body.quality_mode
    initial_state["organic_reference_image"] = body.reference_image
    initial_state["organic_constraints"] = body.constraints
    initial_state["organic_warnings"] = []
```

### Step 4: 添加 confirm_job_endpoint organic 分支

在 `confirm_job_endpoint` 中，构建 resume_data 时添加 organic 分支：

```python
# 在 resume_data 构建部分
is_organic = job.input_type == "organic"

resume_data: dict[str, Any] = {
    "disclaimer_accepted": body.disclaimer_accepted,
    "status": "confirmed",
}

if is_organic:
    # Organic 使用 confirmed_spec 传递字符串覆盖值
    if body.confirmed_spec:
        spec_overrides = body.confirmed_spec
        if "quality_mode" in spec_overrides:
            resume_data["organic_quality_mode"] = spec_overrides["quality_mode"]
        if "provider" in spec_overrides:
            resume_data["organic_provider"] = spec_overrides["provider"]
        if "prompt_en" in spec_overrides or "bounding_box" in spec_overrides:
            # 更新 organic_spec 中的用户编辑字段
            resume_data["confirmed_spec"] = spec_overrides
else:
    # Text/Drawing 使用 confirmed_params (dict[str, float])
    resume_data["confirmed_params"] = body.confirmed_params
    resume_data["confirmed_spec"] = body.confirmed_spec
```

### Step 5: 运行回归测试

Run: `uv run pytest tests/ -v`
Expected: 全部通过

### Step 6: Commit

```bash
git add backend/graph/state.py backend/api/v1/jobs.py
git commit -m "feat(organic): extend CadJobState + API for organic LangGraph migration"
```

---

## Task 2: Organic 节点实现 `[backend]`

**Phase 1a — 可与 Task 3 并行（修改 nodes/organic.py 新文件，无交叉）**

**Skill:** `@streaming-api-patterns`

**Files:**
- Create: `backend/graph/nodes/organic.py`
- Reference: `backend/graph/nodes/analysis.py:60-116` (analyze_intent_node 模式)
- Reference: `backend/core/organic_spec_builder.py` (OrganicSpecBuilder)
- Reference: `backend/infra/mesh_providers/base.py` (MeshProvider 接口)
- Reference: `backend/core/mesh_post_processor.py` (MeshPostProcessor)
- Reference: `backend/models/organic.py` (OrganicSpec, OrganicGenerateRequest, MeshStats)
- Test: `tests/test_organic_nodes.py` (Task 5 编写)

### Step 1: 编写 analyze_organic_node 测试

创建 `tests/test_organic_nodes.py`（先写 analyze 部分的测试）：

```python
"""Tests for organic graph nodes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.graph.nodes.organic import analyze_organic_node


@pytest.fixture
def base_state():
    return {
        "job_id": "test-organic-001",
        "input_type": "organic",
        "input_text": "一个小熊雕塑",
        "organic_provider": "auto",
        "organic_quality_mode": "standard",
        "organic_reference_image": None,
        "organic_constraints": None,
        "organic_warnings": [],
        "status": "created",
    }


@pytest.mark.asyncio
async def test_analyze_organic_success(base_state):
    mock_spec = {
        "prompt_en": "A small bear sculpture",
        "prompt_original": "一个小熊雕塑",
        "shape_category": "figurine",
        "suggested_bounding_box": [80, 60, 100],
        "final_bounding_box": [80, 60, 100],
        "engineering_cuts": [],
        "quality_mode": "standard",
    }
    with patch("backend.graph.nodes.organic.OrganicSpecBuilder") as MockBuilder:
        instance = MockBuilder.return_value
        instance.build = AsyncMock(return_value=MagicMock(model_dump=lambda: mock_spec))
        result = await analyze_organic_node(base_state)

    assert result["status"] == "awaiting_confirmation"
    assert result["organic_spec"] == mock_spec


@pytest.mark.asyncio
async def test_analyze_organic_timeout(base_state):
    with patch("backend.graph.nodes.organic.OrganicSpecBuilder") as MockBuilder:
        instance = MockBuilder.return_value
        instance.build = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await analyze_organic_node(base_state)

    assert result["status"] == "failed"
    assert result["failure_reason"] == "timeout"
```

### Step 2: 运行测试确认失败

Run: `uv run pytest tests/test_organic_nodes.py -v`
Expected: FAIL (ModuleNotFoundError: backend.graph.nodes.organic)

### Step 3: 实现 analyze_organic_node

创建 `backend/graph/nodes/organic.py`：

```python
"""Organic graph nodes: spec building, mesh generation, post-processing."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.core.organic_spec_builder import OrganicSpecBuilder
from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState
from backend.models.job import update_job as _update_job
from backend.models.organic import OrganicConstraints, OrganicGenerateRequest

logger = logging.getLogger(__name__)

LLM_TIMEOUT_S = 60


async def _safe_update_job(job_id: str, **kwargs: Any) -> None:
    """Update DB job, tolerating missing records (e.g. in unit tests)."""
    try:
        await _update_job(job_id, **kwargs)
    except (KeyError, Exception) as exc:
        logger.debug("_safe_update_job(%s) skipped: %s", job_id, exc)


async def analyze_organic_node(state: CadJobState) -> dict[str, Any]:
    """Build OrganicSpec via LLM, dispatch spec_ready event, pause for HITL."""
    job_id = state["job_id"]
    input_text = state.get("input_text") or ""
    constraints_raw = state.get("organic_constraints")
    quality_mode = state.get("organic_quality_mode") or "standard"

    # Build OrganicGenerateRequest from state
    constraints = OrganicConstraints(**(constraints_raw or {}))
    request = OrganicGenerateRequest(
        prompt=input_text,
        reference_image=state.get("organic_reference_image"),
        constraints=constraints,
        quality_mode=quality_mode,
        provider=state.get("organic_provider") or "auto",
    )

    builder = OrganicSpecBuilder()
    try:
        spec = await asyncio.wait_for(builder.build(request), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        error_msg = f"Organic spec 构建超时（{LLM_TIMEOUT_S}s）"
        await _safe_update_job(job_id, status="failed", error=error_msg)
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": error_msg,
            "failure_reason": "timeout", "status": "failed",
        })
        return {"error": error_msg, "failure_reason": "timeout", "status": "failed"}
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    spec_dict = spec.model_dump()

    # Dispatch spec_ready event with full spec for frontend confirmation UI
    await _safe_dispatch("job.organic_spec_ready", {
        "job_id": job_id,
        "organic_spec": spec_dict,
        "status": "organic_spec_ready",
    })

    # Persist to DB so GET /api/v1/jobs/{id} returns spec on page refresh
    await _safe_update_job(job_id, status="awaiting_confirmation")
    await _safe_dispatch("job.awaiting_confirmation", {
        "job_id": job_id, "status": "awaiting_confirmation",
    })

    return {"organic_spec": spec_dict, "status": "awaiting_confirmation"}
```

### Step 4: 运行 analyze 测试确认通过

Run: `uv run pytest tests/test_organic_nodes.py::test_analyze_organic_success tests/test_organic_nodes.py::test_analyze_organic_timeout -v`
Expected: PASS

### Step 5: 实现 generate_organic_mesh_node

在 `backend/graph/nodes/organic.py` 中追加：

```python
async def generate_organic_mesh_node(state: CadJobState) -> dict[str, Any]:
    """Create MeshProvider, generate raw mesh, dispatch progress events."""
    job_id = state["job_id"]

    # Idempotent: skip if mesh already exists
    raw_mesh = state.get("raw_mesh_path")
    if raw_mesh and Path(raw_mesh).exists():
        logger.info("Mesh already exists at %s, skipping generation", raw_mesh)
        return {}

    from backend.infra.mesh_providers import create_provider
    from backend.models.organic import OrganicSpec

    provider_name = state.get("organic_provider") or "auto"
    spec_dict = state.get("organic_spec") or {}
    spec = OrganicSpec(**spec_dict)

    # Read reference image if uploaded
    reference_image_bytes: bytes | None = None
    ref_id = state.get("organic_reference_image")
    if ref_id:
        reference_image_bytes = await _load_reference_image(ref_id)

    await _safe_dispatch("job.generating", {
        "job_id": job_id, "stage": "mesh_generation", "status": "generating",
    })
    await _safe_update_job(job_id, status="generating")

    provider = create_provider(provider_name)

    # Bridge sync on_progress callback to dispatch keepalive SSE events.
    # provider.generate() may run sync loops internally; use sync dispatch.
    import threading
    loop = asyncio.get_running_loop()

    def _on_progress(stage: str, progress: float) -> None:
        """Sync callback safe to call from provider's internal thread."""
        asyncio.run_coroutine_threadsafe(
            _safe_dispatch("job.generating", {
                "job_id": job_id, "stage": stage, "progress": progress,
                "status": "generating",
            }),
            loop,
        )

    try:
        result_path = await provider.generate(
            spec, reference_image=reference_image_bytes, on_progress=_on_progress,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    return {"raw_mesh_path": str(result_path), "status": "generating"}


async def _load_reference_image(file_id: str) -> bytes | None:
    """Load uploaded reference image by file_id."""
    upload_dir = Path("outputs") / "organic" / "uploads"
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = upload_dir / f"{file_id}{ext}"
        if path.exists():
            return await asyncio.to_thread(path.read_bytes)
    logger.warning("Reference image not found for file_id=%s", file_id)
    return None
```

### Step 6: 实现 postprocess_organic_node

在 `backend/graph/nodes/organic.py` 中追加：

```python
async def postprocess_organic_node(state: CadJobState) -> dict[str, Any]:
    """Run full post-processing pipeline via asyncio.to_thread for CPU-bound ops."""
    job_id = state["job_id"]
    raw_mesh_path = state.get("raw_mesh_path")
    if not raw_mesh_path:
        return {"error": "No raw_mesh_path in state", "status": "failed"}

    spec_dict = state.get("organic_spec") or {}
    quality_mode = state.get("organic_quality_mode") or "standard"
    warnings: list[str] = []

    from backend.core.mesh_post_processor import MeshPostProcessor

    job_dir = Path("outputs") / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    async def _dispatch_step(step: str, step_status: str, message: str = "",
                             progress: float = 0.0) -> None:
        await _safe_dispatch("job.post_processing", {
            "job_id": job_id, "step": step, "step_status": step_status,
            "message": message, "progress": progress,
        })

    try:
        # 1. Load
        await _dispatch_step("load", "running", "Loading mesh...")
        mesh = await asyncio.to_thread(MeshPostProcessor.load_mesh, Path(raw_mesh_path))
        await _dispatch_step("load", "success", "Mesh loaded", 0.15)

        # 2. Repair
        await _dispatch_step("repair", "running", "Repairing mesh...")
        mesh, repair_info = await asyncio.to_thread(MeshPostProcessor.repair_mesh, mesh)
        if repair_info.status == "degraded":
            warnings.append(f"Mesh repair degraded: {repair_info.message}")
        await _dispatch_step("repair", "success", repair_info.message, 0.30)

        # 3. Scale
        target_bbox = spec_dict.get("final_bounding_box")
        if target_bbox:
            await _dispatch_step("scale", "running", "Scaling mesh...")
            mesh = await asyncio.to_thread(
                MeshPostProcessor.scale_mesh, mesh, tuple(target_bbox),
            )
            await _dispatch_step("scale", "success", "Mesh scaled", 0.45)
        else:
            await _dispatch_step("scale", "skipped", "No target bounding box", 0.45)

        # 4. Boolean cuts
        engineering_cuts = spec_dict.get("engineering_cuts", [])
        boolean_cuts_applied = 0
        if quality_mode == "draft" or not engineering_cuts:
            await _dispatch_step("boolean", "skipped", "Draft mode or no cuts", 0.60)
        else:
            await _dispatch_step("boolean", "running", "Applying boolean cuts...")
            try:
                mesh, cuts_applied, cut_warnings = await asyncio.to_thread(
                    MeshPostProcessor.apply_boolean_cuts, mesh, engineering_cuts,
                )
                boolean_cuts_applied = cuts_applied
                warnings.extend(cut_warnings)
                await _dispatch_step("boolean", "success",
                                     f"{cuts_applied} cuts applied", 0.60)
            except Exception as exc:
                warnings.append(f"Boolean cuts failed: {exc}")
                await _dispatch_step("boolean", "failed", str(exc), 0.60)

        # 5. Validate
        await _dispatch_step("validate", "running", "Validating mesh...")
        stats = await asyncio.to_thread(
            MeshPostProcessor.validate_mesh, mesh, boolean_cuts_applied,
        )
        stats_dict = stats.model_dump()
        await _dispatch_step("validate", "success", "Mesh valid", 0.75)

        # 6. Export GLB/STL/3MF
        await _dispatch_step("export", "running", "Exporting formats...")
        glb_path = job_dir / "model.glb"
        stl_path = job_dir / "model.stl"
        threemf_path = job_dir / "model.3mf"

        await asyncio.to_thread(mesh.export, str(glb_path), file_type="glb")
        await asyncio.to_thread(mesh.export, str(stl_path), file_type="stl")

        threemf_url: str | None = None
        try:
            await asyncio.to_thread(mesh.export, str(threemf_path), file_type="3mf")
            threemf_url = f"/outputs/{job_id}/model.3mf"
        except Exception as exc:
            warnings.append(f"3MF export failed: {exc}")

        model_url = f"/outputs/{job_id}/model.glb"
        stl_url = f"/outputs/{job_id}/model.stl"
        await _dispatch_step("export", "success", "Export complete", 0.90)

        # 7. Printability check
        printability_result: dict | None = None
        try:
            from backend.core.printability_checker import PrintabilityChecker
            checker = PrintabilityChecker()
            printability_result = await asyncio.to_thread(checker.check, str(stl_path))
        except Exception as exc:
            warnings.append(f"Printability check failed: {exc}")

        await _dispatch_step("printability", "success", "Post-processing complete", 1.0)

        organic_result = {
            "model_url": model_url,
            "stl_url": stl_url,
            "threemf_url": threemf_url,
            "mesh_stats": stats_dict,
            "warnings": warnings,
            "printability": printability_result,
        }

        return {
            "model_url": model_url,
            "mesh_stats": stats_dict,
            "organic_warnings": warnings,
            "organic_result": organic_result,
            "printability": printability_result,
            "status": "post_processed",
        }

    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}
```

### Step 7: 运行全部 analyze 测试

Run: `uv run pytest tests/test_organic_nodes.py -v`
Expected: PASS

### Step 8: Commit

```bash
git add backend/graph/nodes/organic.py tests/test_organic_nodes.py
git commit -m "feat(organic): implement analyze/generate/postprocess organic nodes"
```

---

## Task 3: finalize_node 扩展 `[backend]`

**Phase 1b — 可与 Task 2 并行（修改 nodes/lifecycle.py，无交叉）**

**Files:**
- Modify: `backend/graph/nodes/lifecycle.py:57-99` (finalize_node)
- Test: 在 Task 5.5 中覆盖

### Step 1: 修改 finalize_node organic 分支

在 `backend/graph/nodes/lifecycle.py` 的 `finalize_node` 函数中，扩展 result 组装逻辑：

```python
# 在 result_dict 构建部分（约第 78-85 行之后）添加 organic 分支
input_type = state.get("input_type", "text")

if input_type == "organic" and not is_failed:
    organic_result = state.get("organic_result") or {}
    result_dict.update({
        "model_url": organic_result.get("model_url"),
        "stl_url": organic_result.get("stl_url"),
        "threemf_url": organic_result.get("threemf_url"),
        "mesh_stats": organic_result.get("mesh_stats"),
        "warnings": organic_result.get("warnings", []),
        "printability": organic_result.get("printability"),
    })
```

同时更新 terminal 事件 payload：

```python
# 在 payload 构建部分（约第 88-95 行），添加 organic 字段
payload = {
    "job_id": state["job_id"],
    "status": final_status,
    "error": state.get("error") if is_failed else None,
    "model_url": state.get("model_url") if not is_failed else None,
    "printability": state.get("printability") if not is_failed else None,
}
if input_type == "organic" and not is_failed:
    organic_result = state.get("organic_result") or {}
    payload.update({
        "stl_url": organic_result.get("stl_url"),
        "threemf_url": organic_result.get("threemf_url"),
        "mesh_stats": organic_result.get("mesh_stats"),
        "warnings": organic_result.get("warnings", []),
    })
```

### Step 2: 运行回归测试

Run: `uv run pytest tests/ -v -k "not organic_api"`
Expected: 全部通过

### Step 3: Commit

```bash
git add backend/graph/nodes/lifecycle.py
git commit -m "feat(organic): extend finalize_node for organic result assembly"
```

---

## Task 4: 图拓扑更新 `[backend]`

**Phase 2 — 串行（连接节点和路由，依赖 Task 2）**

**Files:**
- Modify: `backend/graph/builder.py:29-70`
- Modify: `backend/graph/routing.py:13-20`
- Modify: `backend/graph/nodes/analysis.py:156-161` (删除 stub)

### Step 1: 删除 stub_organic_node

从 `backend/graph/nodes/analysis.py` 中删除 `stub_organic_node` 函数（第 156-161 行）及其在文件顶部的任何引用。

### Step 2: 更新 builder.py

修改 `backend/graph/builder.py`：

```python
# 替换 import
# 旧: from backend.graph.nodes.analysis import analyze_intent_node, analyze_vision_node, stub_organic_node
# 新:
from backend.graph.nodes.analysis import analyze_intent_node, analyze_vision_node
from backend.graph.nodes.organic import (
    analyze_organic_node,
    generate_organic_mesh_node,
    postprocess_organic_node,
)

# 替换 stub_organic 节点注册（约第 37 行）
# 旧: workflow.add_node("stub_organic", stub_organic_node)
# 新:
workflow.add_node("analyze_organic", analyze_organic_node)
workflow.add_node("generate_organic_mesh", generate_organic_mesh_node)
workflow.add_node("postprocess_organic", postprocess_organic_node)

# 更新 create_job 后的条件边（约第 48-52 行）
# 旧: {"text": "analyze_intent", "drawing": "analyze_vision", "organic": "stub_organic"}
# 新:
workflow.add_conditional_edges(
    "create_job",
    route_by_input_type,
    {"text": "analyze_intent", "drawing": "analyze_vision", "organic": "analyze_organic"},
)

# 更新 confirm 后的条件边（约第 58-62 行）
# 旧: {"text": "generate_step_text", "drawing": "generate_step_drawing", "finalize": "finalize"}
# 新:
workflow.add_conditional_edges(
    "confirm_with_user",
    route_after_confirm,
    {
        "text": "generate_step_text",
        "drawing": "generate_step_drawing",
        "organic": "generate_organic_mesh",
        "finalize": "finalize",
    },
)

# 添加 organic 后续边
workflow.add_edge("generate_organic_mesh", "postprocess_organic")
workflow.add_edge("postprocess_organic", "finalize")
```

### Step 3: 更新 routing.py

修改 `backend/graph/routing.py` 第 18-19 行：

```python
def route_after_confirm(state: CadJobState) -> str:
    if state.get("status") == "failed":
        return "finalize"
    input_type = state["input_type"]
    # Organic 现在走 generate_organic_mesh，不再跳过
    return input_type  # "text" | "drawing" | "organic"
```

### Step 4: 运行回归测试

Run: `uv run pytest tests/ -v`
Expected: 全部通过

### Step 5: Commit

```bash
git add backend/graph/builder.py backend/graph/routing.py backend/graph/nodes/analysis.py
git commit -m "feat(organic): update graph topology — 3 new organic nodes replace stub"
```

---

## Task 5: 单元测试 `[backend]` `[test]`

**Phase 3 — 串行（依赖 Task 2, 3, 4）**

**Skill:** `@qa-testing-strategy`, `@test-automation-framework`

**Files:**
- Modify: `tests/test_organic_nodes.py` (已在 Task 2 创建基础)
- Modify: `tests/test_organic_api.py` (迁移)

### Step 1: 补充 generate_organic_mesh_node 测试

在 `tests/test_organic_nodes.py` 中添加：

```python
from backend.graph.nodes.organic import generate_organic_mesh_node


@pytest.mark.asyncio
async def test_generate_mesh_success(base_state):
    base_state["organic_spec"] = {
        "prompt_en": "bear", "shape_category": "figurine",
        "final_bounding_box": [80, 60, 100], "engineering_cuts": [],
        "quality_mode": "standard",
    }
    mock_path = Path("/tmp/test_mesh.glb")
    with patch("backend.graph.nodes.organic.create_provider") as mock_create:
        provider = AsyncMock()
        provider.generate = AsyncMock(return_value=mock_path)
        mock_create.return_value = provider
        result = await generate_organic_mesh_node(base_state)

    assert result["raw_mesh_path"] == str(mock_path)
    assert result["status"] == "generating"


@pytest.mark.asyncio
async def test_generate_mesh_idempotent(base_state, tmp_path):
    mesh_file = tmp_path / "existing.glb"
    mesh_file.write_bytes(b"fake")
    base_state["raw_mesh_path"] = str(mesh_file)
    result = await generate_organic_mesh_node(base_state)
    assert result == {}


@pytest.mark.asyncio
async def test_generate_mesh_provider_failure(base_state):
    base_state["organic_spec"] = {"prompt_en": "bear", "quality_mode": "standard"}
    with patch("backend.graph.nodes.organic.create_provider") as mock_create:
        provider = AsyncMock()
        provider.generate = AsyncMock(side_effect=RuntimeError("API down"))
        mock_create.return_value = provider
        result = await generate_organic_mesh_node(base_state)

    assert result["status"] == "failed"
    assert result["failure_reason"] == "generation_error"
```

### Step 2: 补充 postprocess_organic_node 测试

```python
from backend.graph.nodes.organic import postprocess_organic_node


@pytest.mark.asyncio
async def test_postprocess_success(base_state, tmp_path):
    mesh_file = tmp_path / "raw.glb"
    mesh_file.write_bytes(b"fake")
    base_state["raw_mesh_path"] = str(mesh_file)
    base_state["organic_spec"] = {
        "final_bounding_box": [80, 60, 100],
        "engineering_cuts": [],
    }

    with patch("backend.graph.nodes.organic.MeshPostProcessor") as MockPP:
        mock_mesh = MagicMock()
        mock_mesh.export = MagicMock()
        MockPP.load_mesh.return_value = mock_mesh
        MockPP.repair_mesh.return_value = (mock_mesh, MagicMock(status="success", message="ok"))
        MockPP.scale_mesh.return_value = mock_mesh
        MockPP.validate_mesh.return_value = MagicMock(model_dump=lambda: {"vertex_count": 100})

        with patch("backend.graph.nodes.organic.PrintabilityChecker"):
            result = await postprocess_organic_node(base_state)

    assert result["status"] == "post_processed"
    assert "organic_result" in result
    assert result["organic_result"]["model_url"].endswith("/model.glb")


@pytest.mark.asyncio
async def test_postprocess_boolean_failure_degraded(base_state, tmp_path):
    mesh_file = tmp_path / "raw.glb"
    mesh_file.write_bytes(b"fake")
    base_state["raw_mesh_path"] = str(mesh_file)
    base_state["organic_spec"] = {
        "final_bounding_box": [80, 60, 100],
        "engineering_cuts": [{"type": "flat_bottom"}],
    }
    base_state["organic_quality_mode"] = "high"

    with patch("backend.graph.nodes.organic.MeshPostProcessor") as MockPP:
        mock_mesh = MagicMock()
        mock_mesh.export = MagicMock()
        MockPP.load_mesh.return_value = mock_mesh
        MockPP.repair_mesh.return_value = (mock_mesh, MagicMock(status="success", message="ok"))
        MockPP.scale_mesh.return_value = mock_mesh
        MockPP.apply_boolean_cuts.side_effect = RuntimeError("manifold3d crash")
        MockPP.validate_mesh.return_value = MagicMock(model_dump=lambda: {"vertex_count": 100})

        with patch("backend.graph.nodes.organic.PrintabilityChecker"):
            result = await postprocess_organic_node(base_state)

    assert result["status"] == "post_processed"  # 降级成功
    assert any("Boolean cuts failed" in w for w in result["organic_warnings"])
```

### Step 3: 补充路由和 finalize 测试

```python
from backend.graph.routing import route_after_confirm


def test_route_after_confirm_organic():
    state = {"input_type": "organic", "status": "confirmed"}
    assert route_after_confirm(state) == "organic"


def test_route_after_confirm_failed():
    state = {"input_type": "organic", "status": "failed"}
    assert route_after_confirm(state) == "finalize"
```

### Step 4: 补充 confirm 合并语义测试

```python
@pytest.mark.asyncio
async def test_organic_confirm_merges_spec_overrides(base_state):
    """Verify confirmed_spec overrides are correctly structured for resume."""
    from backend.api.v1.jobs import ConfirmRequest

    body = ConfirmRequest(
        confirmed_spec={
            "prompt_en": "A cute bear toy",
            "quality_mode": "high",
            "provider": "tripo3d",
            "bounding_box": [100, 80, 120],
        },
        disclaimer_accepted=True,
    )
    # confirmed_params should remain dict[str, float] for text/drawing
    assert isinstance(body.confirmed_params, dict)
    # confirmed_spec should be dict[str, Any] for organic
    assert body.confirmed_spec["prompt_en"] == "A cute bear toy"
    assert body.confirmed_spec["provider"] == "tripo3d"
```

### Step 5: 迁移 test_organic_api.py

检查 `tests/test_organic_api.py` 中的测试：
- 依赖旧 `/api/v1/organic` 端点的测试 → 删除或改写为 `/api/v1/jobs` organic 模式
- 依赖 OrganicSpecBuilder/MeshProvider 的纯单元测试 → 保留

### Step 6: 运行全部测试

Run: `uv run pytest tests/ -v`
Expected: 全部通过

### Step 7: Commit

```bash
git add tests/
git commit -m "test(organic): comprehensive tests for organic nodes, routing, confirm"
```

---

## Task 6: 后端清理 `[backend]`

**Phase 4a — 可与 Task 7 并行（修改 organic.py/router.py/jobs.py，与前端无交叉）**

**Files:**
- Modify: `backend/api/v1/jobs.py` (添加 organic-providers + upload-reference 端点)
- Modify: `backend/api/v1/router.py:35` (移除 organic_router)
- Delete: `backend/api/v1/organic.py`

### Step 1: 迁移 /providers 端点到 jobs router

从 `backend/api/v1/organic.py` 的 `@router.get("/providers")` 函数（约第 391 行）提取核心逻辑，在 `backend/api/v1/jobs.py` 中添加：

```python
@router.get("/organic-providers")
async def get_organic_providers():
    """Return available organic mesh generation providers and their status."""
    from backend.infra.mesh_providers import get_available_providers
    return await get_available_providers()
```

### Step 2: 迁移 /upload 端点到 jobs router

从 `backend/api/v1/organic.py` 的 `@router.post("/upload")` 函数（约第 340 行）提取核心逻辑：

```python
@router.post("/upload-reference")
async def upload_reference_image(file: UploadFile = File(...)):
    """Upload a reference image for organic generation (PNG/JPEG/WEBP only)."""
    # 复用 organic.py 中的上传逻辑：
    # MIME 校验 → 大小校验 → 保存到 outputs/organic/uploads/{file_id}.{ext}
    # 返回 {"file_id": file_id, "filename": file.filename}
```

### Step 3: 从 router.py 移除 organic_router

修改 `backend/api/v1/router.py`，删除 organic_router 的 import 和 include：

```python
# 删除: from backend.api.v1.organic import router as organic_router
# 删除: api_router.include_router(organic_router, prefix="/organic")
```

### Step 4: 删除 organic.py

```bash
rm backend/api/v1/organic.py
```

### Step 5: 运行测试验证 404

Run: `uv run pytest tests/ -v`
Expected: 通过（旧 organic 测试已在 Task 5.7 迁移/删除）

### Step 6: Commit

```bash
git add backend/api/v1/jobs.py backend/api/v1/router.py
git rm backend/api/v1/organic.py
git commit -m "refactor(organic): migrate endpoints to jobs router, delete organic.py"
```

---

## Task 7: 前端改造 `[frontend]`

**Phase 4b — 可与 Task 6 并行（仅修改 frontend/ 目录，无交叉）**

**Skill:** `@frontend-design`, `@ant-design`

**Files:**
- Modify: `frontend/src/pages/OrganicGenerate/OrganicWorkflow.tsx`
- Modify: `frontend/src/pages/OrganicGenerate/` (相关组件)
- Modify: `frontend/src/services/` (API 调用)

### Step 1: 修改 useOrganicWorkflow hook

将 API 调用从 `/api/v1/organic` 改为 `/api/v1/jobs`：

```typescript
// 旧: POST /api/v1/organic
// 新: POST /api/v1/jobs
const response = await fetch('/api/v1/jobs', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    input_type: 'organic',
    text: prompt,           // 或 prompt 字段
    provider: selectedProvider,
    quality_mode: qualityMode,
    reference_image: referenceImageId,
    constraints: {
      bounding_box: boundingBox,
      engineering_cuts: engineeringCuts,
    },
  }),
});
```

### Step 2: 适配 SSE 事件名

将 `event: "organic"` 改为 `job.*` 事件：

```typescript
// 旧: eventSource.addEventListener('organic', handler)
// 新: 解析 event.data 中的 event 字段
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch (data.event || event.type) {
    case 'job.organic_spec_ready':
      // 展示确认 UI
      break;
    case 'job.awaiting_confirmation':
      // 暂停等待用户确认
      break;
    case 'job.generating':
      // 更新生成进度
      break;
    case 'job.post_processing':
      // 更新后处理步骤
      break;
    case 'job.completed':
      // 提取 organic_result
      break;
    case 'job.failed':
      // 显示错误
      break;
  }
};
```

### Step 3: 新增 organic spec 确认界面

创建确认组件，展示 OrganicSpec 字段并允许用户编辑：

```typescript
// OrganicSpecConfirmation.tsx
// 展示: prompt_en, shape_category, bounding_box, engineering_cuts, quality_mode, provider
// 用户可编辑后点击确认 → POST /api/v1/jobs/{id}/confirm
const confirmSpec = async () => {
  await fetch(`/api/v1/jobs/${jobId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      confirmed_spec: {
        prompt_en: editedPrompt,
        bounding_box: editedBBox,
        quality_mode: editedQuality,
        provider: editedProvider,
      },
      disclaimer_accepted: true,
    }),
  });
};
```

### Step 4: 适配 completed 事件 payload

```typescript
case 'job.completed':
  const result = data;
  setModelUrl(result.model_url);
  setStlUrl(result.stl_url);
  setThreemfUrl(result.threemf_url);
  setMeshStats(result.mesh_stats);
  setWarnings(result.warnings || []);
  setPrintability(result.printability);
  break;
```

### Step 5: TypeScript 编译验证

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: 零错误

### Step 6: Commit

```bash
cd frontend && git add . && git commit -m "feat(organic): adapt frontend to unified /api/v1/jobs + HITL confirmation UI"
```

---

## Task 8: 集成验证 `[backend]` `[frontend]` `[test]`

**Phase 5 — 串行（依赖所有前序任务）**

**Skill:** `@qa-testing-strategy`

### Step 1: 全量后端测试

Run: `uv run pytest tests/ -v`
Expected: 全部通过

### Step 2: TypeScript 编译验证

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: 零错误

### Step 3: 端到端冒烟测试

启动后端和前端：
```bash
./scripts/start-v3.sh
```

分别测试三种 input_type：
1. **Text**: `POST /api/v1/jobs` (input_type=text) → 确认 → 生成 → 完成
2. **Drawing**: `POST /api/v1/jobs/upload` (input_type=drawing) → 确认 → 生成 → 完成
3. **Organic**: `POST /api/v1/jobs` (input_type=organic, text="一个小熊雕塑") → 确认 → 生成 → 完成

### Step 4: HITL 中断/恢复验证

1. 创建 organic job
2. 等待 `job.organic_spec_ready` 事件
3. 确认 spec（编辑 prompt_en + quality_mode）
4. 验证生成使用编辑后的参数
5. 等待 `job.completed`

### Step 5: 回归验证

确认 text 和 drawing 管道功能不受 organic 迁移影响：
- Text 参数确认 + STEP 生成 ✓
- Drawing 图纸分析 + 参数确认 + STEP 生成 ✓

### Step 6: 验证旧端点 404

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8780/api/v1/organic
# Expected: 404
```

### Step 7: Final commit

```bash
git add -A
git commit -m "feat(organic): complete organic LangGraph migration with HITL + SSE"
```
