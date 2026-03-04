# Pipeline Config Fullstack — Agent Team Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补全管线配置全栈能力——运行时节点跳过、策略可用性 API、Schema 驱动前端表单、HITL 中调参、e2e 验证。

**Architecture:** 后端 `_wrap_node()` 运行时跳过 + `node.skipped` SSE；resolver `include_disabled` 参数；Pydantic v2 原生 schema + x-sensitive 后处理；前端 SchemaForm 动态渲染；ValidationBanner + AbortController；confirm 端点通过 resume_data 传递 config 更新。

**Tech Stack:** Python 3.10+ / FastAPI / LangGraph / Pydantic v2 / React / Ant Design / TypeScript

**Design doc:** `docs/plans/2026-03-04-pipeline-config-fullstack-design.md`
**OpenSpec:** `openspec/changes/pipeline-config-fullstack/`

---

## Agent Team 执行拓扑

```
Phase 0 (串行, Team Lead): 接口定义 — 消除并行文件冲突
    ↓
Phase 1 (并行, 3 agents): [T1 || T2 || T3] 后端核心能力
    ↓
Phase 2 (串行, Team Lead): 集成 Phase 1 + T4 confirm 扩展 + T5 前端类型
    ↓
Phase 3 (并行, 2 agents): [T6 || T7] 前端组件
    ↓
Phase 4 (串行, Team Lead): 集成 Phase 3 + T8 ValidationBanner + T9 HITL Dialog
    ↓
Phase 5 (串行, Team Lead): T10 E2E 测试
    ↓
Phase 6: Review Team
```

### 文件交叉矩阵

| Task | 修改文件 | 冲突风险 |
|------|---------|---------|
| T1 | `builder.py`, `resolver.py`, `pipeline_config.py`(validate) | T2 共享 pipeline_config.py |
| T2 | `pipeline_config.py`(新端点) | T1 共享 pipeline_config.py |
| T3 | `registry.py` | 无 |
| T4 | `jobs.py`, `graph/nodes/confirm.py` | 无 |
| T5 | `types/pipeline.ts`, `services/api.ts` | 无 |
| T6 | `components/SchemaForm/index.tsx`(新) | 无 |
| T7 | `components/PipelineConfigBar/CustomPanel.tsx`, `index.tsx` | T8 共享 index.tsx |
| T8 | `components/PipelineConfigBar/ValidationBanner.tsx`(新), `index.tsx` | T7 共享 |
| T9 | `pages/Generate/GenerateWorkflow.tsx` | 无 |
| T10 | `frontend/e2e/pipeline-config.spec.ts`(新) | 无 |

**Phase 0 解决方案**: 在 `pipeline_config.py` 预留 `get_strategy_availability` 空路由 + validate 函数签名，T1/T2 各自填充不同函数体。

---

## Phase 0: 接口定义 (Team Lead)

**目标**: 预定义共享接口，使 Phase 1 三个 agent 可在各自 worktree 中无冲突工作。

### 0.1 resolver.py — 添加 `include_disabled` 参数签名

在 `backend/graph/resolver.py` 的 `resolve()` 方法签名中添加参数：

```python
@classmethod
def resolve(
    cls,
    reg: NodeRegistry,
    pipeline_config: dict[str, dict[str, Any]],
    input_type: str | None,
    *,
    include_disabled: bool = True,  # NEW: Phase 0 接口定义
) -> ResolvedPipeline:
```

Step 1 过滤逻辑改为：
```python
        # Step 1: filter enabled + input_type
        candidates: dict[str, NodeDescriptor] = {}
        for name, desc in all_nodes.items():
            node_config = pipeline_config.get(name, {})
            if not include_disabled and not node_config.get("enabled", True):
                continue
            if input_type and input_type not in desc.input_types:
                continue
            candidates[name] = desc
```

### 0.2 pipeline_config.py — 预留路由签名

在文件末尾添加空路由：

```python
@router.get("/strategy-availability")
async def get_strategy_availability() -> dict[str, Any]:
    """返回各节点策略的运行时可用性。(T2 实现)"""
    raise NotImplementedError("Phase 1 T2 will implement")
```

### 0.3 registry.py — 预留 enhance 函数

```python
def enhance_config_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Post-process Pydantic v2 schema: inject x-sensitive for sensitive fields. (T3 实现)"""
    return schema  # placeholder
```

### 0.4 Commit

```bash
git add backend/graph/resolver.py backend/api/v1/pipeline_config.py backend/graph/registry.py
git commit -m "feat(pipeline-config): Phase 0 — interface stubs for parallel backend work"
```

---

## Phase 1: 并行后端 (3 Agents)

### Task 1: 运行时节点跳过 [Agent-BE1]

**Files:**
- Modify: `backend/graph/builder.py:108-180` — `_wrap_node()` 增加 enabled 检查 + node.skipped SSE
- Modify: `backend/api/v1/pipeline_config.py:validate` — 使用 `include_disabled=False` + 全禁用检测
- Create: `tests/test_runtime_skip.py`

**Step 1: Write failing tests**

```python
# tests/test_runtime_skip.py
"""Tests for runtime node skip and resolver include_disabled."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_dispatch():
    """Mock _safe_dispatch to capture SSE events."""
    with patch("backend.graph.builder._safe_dispatch", new_callable=AsyncMock) as m:
        yield m


class TestWrapNodeSkip:
    """_wrap_node() runtime skip behavior."""

    def _make_desc(self, name="test_node", fn=None):
        from backend.graph.descriptor import NodeDescriptor
        return NodeDescriptor(
            name=name,
            display_name="Test",
            fn=fn or AsyncMock(return_value={"out": "val"}),
            requires=[],
            produces=["test_asset"],
            input_types=["text"],
            config_model=None,
            strategies={},
            default_strategy=None,
            fallback_chain=[],
            is_entry=False,
            is_terminal=False,
            supports_hitl=False,
            non_fatal=False,
            description="",
            estimated_duration="",
        )

    def _make_builder(self):
        from backend.graph.builder import GraphBuilder
        builder = GraphBuilder.__new__(GraphBuilder)
        return builder

    def test_skip_emits_events_and_returns_empty(self, mock_dispatch):
        """Disabled node: emit node.started + node.skipped, return {}, don't execute fn."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {
            "job_id": "j1",
            "pipeline_config": {"test_node": {"enabled": False}},
        }

        result = asyncio.get_event_loop().run_until_complete(wrapped(state))

        assert result == {}
        desc.fn.assert_not_called()

        # Verify SSE events
        events = [call.args[0] for call in mock_dispatch.call_args_list]
        assert "node.started" in events
        assert "node.skipped" in events

    def test_enabled_node_executes_normally(self, mock_dispatch):
        """Enabled node executes strategy and returns diff."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {
            "job_id": "j1",
            "pipeline_config": {"test_node": {"enabled": True}},
        }

        result = asyncio.get_event_loop().run_until_complete(wrapped(state))

        assert result != {}
        desc.fn.assert_called_once()

    def test_default_enabled_when_not_in_config(self, mock_dispatch):
        """Node not in pipeline_config defaults to enabled."""
        desc = self._make_desc()
        wrapped = self._make_builder()._wrap_node(desc)

        state = {"job_id": "j1", "pipeline_config": {}}

        result = asyncio.get_event_loop().run_until_complete(wrapped(state))

        assert result != {}
        desc.fn.assert_called_once()


class TestResolverIncludeDisabled:
    """DependencyResolver.resolve() include_disabled parameter."""

    def test_include_disabled_true_keeps_all(self):
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry
        from backend.graph.resolver import DependencyResolver

        discover_nodes()
        all_nodes = list(registry.all().keys())
        if not all_nodes:
            pytest.skip("No nodes registered")

        # Find a non-system node to disable
        target = None
        for name, desc in registry.all().items():
            if not desc.is_entry and not desc.is_terminal and not desc.supports_hitl:
                target = name
                break

        if not target:
            pytest.skip("No toggleable nodes")

        config = {target: {"enabled": False}}
        resolved = DependencyResolver.resolve(registry, config, None, include_disabled=True)
        names = {d.name for d in resolved.ordered_nodes}
        assert target in names, f"{target} should be included when include_disabled=True"

    def test_include_disabled_false_filters(self):
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry
        from backend.graph.resolver import DependencyResolver

        discover_nodes()
        target = None
        for name, desc in registry.all().items():
            if not desc.is_entry and not desc.is_terminal and not desc.supports_hitl:
                target = name
                break

        if not target:
            pytest.skip("No toggleable nodes")

        config = {target: {"enabled": False}}
        resolved = DependencyResolver.resolve(registry, config, None, include_disabled=False)
        names = {d.name for d in resolved.ordered_nodes}
        assert target not in names, f"{target} should be excluded when include_disabled=False"


class TestValidateAllDisabled:
    """POST /pipeline/validate rejects all-disabled config."""

    @pytest.mark.asyncio
    async def test_all_disabled_returns_invalid(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        # Get all nodes first
        nodes_resp = client.get("/api/v1/pipeline/nodes")
        nodes = nodes_resp.json().get("nodes", [])

        # Build config with all toggleable nodes disabled
        config = {}
        for n in nodes:
            if not n.get("is_entry") and not n.get("is_terminal") and not n.get("supports_hitl"):
                config[n["name"]] = {"enabled": False}

        resp = client.post("/api/v1/pipeline/validate", json={
            "config": config,
        })
        data = resp.json()
        assert data["valid"] is False
```

**Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_runtime_skip.py -v
```

**Step 3: Implement `_wrap_node()` skip logic**

In `backend/graph/builder.py`, modify the `wrapped()` function inside `_wrap_node()`:

```python
    async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        job_id = state.get("job_id", "unknown")
        t0 = time.time()

        await _safe_dispatch("node.started", {
            "job_id": job_id,
            "node": desc.name,
            "timestamp": t0,
        })

        # Runtime skip: check if node is disabled in pipeline_config
        node_cfg = state.get("pipeline_config", {}).get(desc.name, {})
        if not node_cfg.get("enabled", True):
            logger.info("Node %s skipped (disabled)", desc.name)
            await _safe_dispatch("node.skipped", {
                "job_id": job_id,
                "node": desc.name,
                "reason": "disabled",
            })
            return {}

        try:
            ctx = NodeContext.from_state(state, desc)
            # ... rest unchanged
```

**Step 4: Implement validate with `include_disabled=False`**

In `backend/api/v1/pipeline_config.py`, update `validate_pipeline_config()`:

```python
    try:
        resolved = DependencyResolver.resolve(registry, config, input_type, include_disabled=False)
        if not resolved.ordered_nodes:
            return {"valid": False, "error": "至少需要启用一个节点", "node_count": 0}
        return {
            "valid": True,
            "node_count": len(resolved.ordered_nodes),
            "topology": [d.name for d in resolved.ordered_nodes],
            "interrupt_before": resolved.interrupt_before,
        }
    except (ValueError, KeyError, TypeError) as exc:
        return {"valid": False, "error": str(exc)}
```

**Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_runtime_skip.py -v
```

**Step 6: Commit**

```bash
git add backend/graph/builder.py backend/api/v1/pipeline_config.py tests/test_runtime_skip.py
git commit -m "feat(graph): runtime node skip with SSE events + resolver include_disabled"
```

---

### Task 2: 策略可用性 API [Agent-BE2]

**Files:**
- Modify: `backend/api/v1/pipeline_config.py` — 实现 `get_strategy_availability`
- Create: `tests/test_strategy_availability.py`

**Step 1: Write failing tests**

```python
# tests/test_strategy_availability.py
"""Tests for GET /pipeline/strategy-availability endpoint."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestStrategyAvailability:
    """Strategy availability API tests."""

    def test_all_available(self):
        """All strategies available → all return available: true."""
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/strategy-availability")
        assert resp.status_code == 200
        data = resp.json()

        # Should be a dict of node → {strategy → {available, reason?}}
        assert isinstance(data, dict)
        for node_name, strategies in data.items():
            assert isinstance(strategies, dict)
            for strat_name, status in strategies.items():
                assert "available" in status
                assert isinstance(status["available"], bool)

    def test_unavailable_with_reason(self):
        """Mock a strategy as unavailable → should return reason."""
        from backend.graph.descriptor import NodeStrategy

        class FakeUnavailable(NodeStrategy):
            def check_available(self) -> bool:
                return False

            @property
            def unavailable_reason(self):
                return "API Key 未配置"

            async def execute(self, ctx):
                pass

        # Patch a strategy in registry
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry

        discover_nodes()
        # Find first node with strategies
        target_node = None
        target_strat = None
        for name, desc in registry.all().items():
            if desc.strategies:
                target_node = name
                target_strat = list(desc.strategies.keys())[0]
                break

        if not target_node:
            pytest.skip("No nodes with strategies")

        original = registry.all()[target_node].strategies[target_strat]
        registry.all()[target_node].strategies[target_strat] = FakeUnavailable

        try:
            from fastapi.testclient import TestClient
            from backend.main import app

            client = TestClient(app)
            resp = client.get("/api/v1/pipeline/strategy-availability")
            data = resp.json()

            assert target_node in data
            assert target_strat in data[target_node]
            assert data[target_node][target_strat]["available"] is False
            assert "reason" in data[target_node][target_strat]
        finally:
            registry.all()[target_node].strategies[target_strat] = original

    def test_instantiation_error(self):
        """Strategy __init__ raises → available: false with error message."""
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry

        discover_nodes()
        target_node = None
        target_strat = None
        for name, desc in registry.all().items():
            if desc.strategies:
                target_node = name
                target_strat = list(desc.strategies.keys())[0]
                break

        if not target_node:
            pytest.skip("No nodes with strategies")

        class BrokenStrategy:
            def __init__(self, config=None):
                raise RuntimeError("Missing GPU driver")

        original = registry.all()[target_node].strategies[target_strat]
        registry.all()[target_node].strategies[target_strat] = BrokenStrategy

        try:
            from fastapi.testclient import TestClient
            from backend.main import app

            client = TestClient(app)
            resp = client.get("/api/v1/pipeline/strategy-availability")
            data = resp.json()

            assert data[target_node][target_strat]["available"] is False
            assert "Missing GPU driver" in data[target_node][target_strat]["reason"]
        finally:
            registry.all()[target_node].strategies[target_strat] = original

    def test_nodes_without_strategies_excluded(self):
        """Nodes with no strategies should not appear in response."""
        from fastapi.testclient import TestClient
        from backend.main import app
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry

        discover_nodes()
        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/strategy-availability")
        data = resp.json()

        for name, desc in registry.all().items():
            if not desc.strategies:
                assert name not in data
```

**Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_strategy_availability.py -v
```

**Step 3: Implement strategy-availability endpoint**

Replace the placeholder in `backend/api/v1/pipeline_config.py`:

```python
@router.get("/strategy-availability")
async def get_strategy_availability() -> dict[str, Any]:
    """返回各节点策略的运行时可用性。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry

    discover_nodes()

    result: dict[str, dict[str, dict[str, Any]]] = {}
    for name, desc in registry.all().items():
        if not desc.strategies:
            continue

        strat_status: dict[str, dict[str, Any]] = {}
        for strat_name, strat_cls in desc.strategies.items():
            try:
                # Instantiate with actual config_model defaults
                config = desc.config_model() if desc.config_model else None
                instance = strat_cls(config=config)
                available = instance.check_available()
                entry: dict[str, Any] = {"available": available}
                if not available:
                    reason = getattr(instance, "unavailable_reason", "不可用")
                    entry["reason"] = reason
                strat_status[strat_name] = entry
            except Exception as exc:
                strat_status[strat_name] = {
                    "available": False,
                    "reason": str(exc),
                }

        result[name] = strat_status

    return result
```

**Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_strategy_availability.py -v
```

**Step 5: Commit**

```bash
git add backend/api/v1/pipeline_config.py tests/test_strategy_availability.py
git commit -m "feat(api): add GET /pipeline/strategy-availability endpoint"
```

---

### Task 3: Config schema x-sensitive 后处理 [Agent-BE3]

**Files:**
- Modify: `backend/graph/registry.py` — 实现 `enhance_config_schema()`
- Modify: `backend/api/v1/pipeline_config.py:list_pipeline_nodes` — 调用 enhance
- Create: `tests/test_schema_sensitive.py`

**Step 1: Write failing tests**

```python
# tests/test_schema_sensitive.py
"""Tests for config schema x-sensitive enhancement."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field


class TestEnhanceConfigSchema:
    """enhance_config_schema() post-processing."""

    def test_sensitive_field_detected(self):
        """Fields named api_key/secret/password get x-sensitive: true."""
        from backend.graph.registry import enhance_config_schema

        class TestConfig(BaseModel):
            api_key: str = ""
            timeout: int = 60

        schema = TestConfig.model_json_schema()
        enhanced = enhance_config_schema(schema)

        props = enhanced["properties"]
        assert props["api_key"].get("x-sensitive") is True
        assert "x-sensitive" not in props["timeout"]

    def test_secret_field_detected(self):
        from backend.graph.registry import enhance_config_schema

        class TestConfig(BaseModel):
            client_secret: str = ""

        schema = TestConfig.model_json_schema()
        enhanced = enhance_config_schema(schema)
        assert enhanced["properties"]["client_secret"].get("x-sensitive") is True

    def test_password_field_detected(self):
        from backend.graph.registry import enhance_config_schema

        class TestConfig(BaseModel):
            db_password: str = ""

        schema = TestConfig.model_json_schema()
        enhanced = enhance_config_schema(schema)
        assert enhanced["properties"]["db_password"].get("x-sensitive") is True

    def test_pydantic_native_metadata_preserved(self):
        """Pydantic v2 native description/min/max/x-group should be present."""
        from backend.graph.registry import enhance_config_schema

        class TestConfig(BaseModel):
            timeout: int = Field(
                default=60,
                ge=10,
                le=600,
                description="超时时间（秒）",
                json_schema_extra={"x-group": "高级"},
            )

        schema = TestConfig.model_json_schema()
        enhanced = enhance_config_schema(schema)

        props = enhanced["properties"]["timeout"]
        assert props.get("description") == "超时时间（秒）"
        assert props.get("minimum") == 10
        assert props.get("maximum") == 600
        assert props.get("x-group") == "高级"

    def test_no_sensitive_fields_unchanged(self):
        """Schema without sensitive fields passes through unchanged."""
        from backend.graph.registry import enhance_config_schema

        class TestConfig(BaseModel):
            timeout: int = 60
            enabled: bool = True

        schema = TestConfig.model_json_schema()
        enhanced = enhance_config_schema(schema)

        for prop in enhanced["properties"].values():
            assert "x-sensitive" not in prop


class TestNodesEndpointSchema:
    """GET /pipeline/nodes returns enhanced config_schema."""

    def test_nodes_include_enhanced_schema(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/nodes")
        data = resp.json()

        # At least one node with config_schema should exist
        schemas = [n.get("config_schema") for n in data["nodes"] if n.get("config_schema")]
        assert len(schemas) > 0  # sanity check
```

**Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_schema_sensitive.py -v
```

**Step 3: Implement `enhance_config_schema()`**

In `backend/graph/registry.py`, replace the placeholder:

```python
import re

_SENSITIVE_PATTERN = re.compile(r"(api_key|secret|password)", re.IGNORECASE)


def enhance_config_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Post-process Pydantic v2 JSON schema: inject x-sensitive for sensitive field names.

    Pydantic v2 natively handles description, minimum/maximum, and json_schema_extra
    (including x-group), so this function only adds x-sensitive detection.
    """
    props = schema.get("properties", {})
    for field_name, field_schema in props.items():
        if _SENSITIVE_PATTERN.search(field_name):
            field_schema["x-sensitive"] = True
    return schema
```

**Step 4: Update `/nodes` endpoint to use `enhance_config_schema()`**

In `backend/api/v1/pipeline_config.py:list_pipeline_nodes()`:

```python
        if desc.config_model:
            from backend.graph.registry import enhance_config_schema
            node_info["config_schema"] = enhance_config_schema(
                desc.config_model.model_json_schema()
            )
```

**Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_schema_sensitive.py -v
```

**Step 6: Commit**

```bash
git add backend/graph/registry.py backend/api/v1/pipeline_config.py tests/test_schema_sensitive.py
git commit -m "feat(registry): x-sensitive schema enhancement for config fields"
```

---

## Phase 2: 集成 + Confirm 扩展 + 前端类型 (Team Lead)

### Phase 2.0: 合并 Phase 1 产出

```bash
# 合并 3 个 agent 的 worktree
git merge agent-be1-branch agent-be2-branch agent-be3-branch
uv run pytest tests/ -v  # 验证集成
```

### Task 4: Confirm 端点扩展 + 旧 API 废弃

**Files:**
- Modify: `backend/api/v1/jobs.py:108-130` — ConfirmRequest 新增字段
- Modify: `backend/api/v1/jobs.py:575-665` — confirm_job 逻辑
- Modify: `backend/api/v1/pipeline_config.py` — Deprecation headers
- Create: `tests/test_confirm_config.py`

**Step 1: Write failing tests**

```python
# tests/test_confirm_config.py
"""Tests for confirm endpoint pipeline_config_updates."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestConfirmRequestModel:
    """ConfirmRequest accepts pipeline_config_updates."""

    def test_with_updates(self):
        from backend.api.v1.jobs import ConfirmRequest
        req = ConfirmRequest(
            confirmed_params={"diameter": 50},
            pipeline_config_updates={"mesh_repair": {"strategy": "trimesh"}},
        )
        assert req.pipeline_config_updates == {"mesh_repair": {"strategy": "trimesh"}}

    def test_without_updates(self):
        from backend.api.v1.jobs import ConfirmRequest
        req = ConfirmRequest(confirmed_params={"diameter": 50})
        assert req.pipeline_config_updates is None

    def test_invalid_format_rejected(self):
        from backend.api.v1.jobs import ConfirmRequest
        with pytest.raises(ValidationError):
            ConfirmRequest(
                confirmed_params={},
                pipeline_config_updates={"mesh_repair": "invalid"},  # must be dict
            )


class TestDeprecationHeaders:
    """Legacy endpoints return Deprecation headers."""

    def test_tooltips_deprecated(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/tooltips")
        assert "Deprecation" in resp.headers

    def test_presets_deprecated(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        resp = client.get("/api/v1/pipeline/presets")
        assert "Deprecation" in resp.headers
```

**Step 2: Run tests — expect FAIL**

**Step 3: Implement**

In `backend/api/v1/jobs.py`, update ConfirmRequest:

```python
class ConfirmRequest(BaseModel):
    """HITL 参数确认请求（统一文本和图纸模式）。"""

    confirmed_params: dict[str, float] = Field(default_factory=dict)
    confirmed_spec: dict[str, Any] | None = None
    base_body_method: str = "extrude"
    disclaimer_accepted: bool = True
    pipeline_config_updates: dict[str, dict] | None = None
```

In `confirm_job()`, include pipeline_config_updates in resume_data:

```python
    resume_data: dict[str, Any] = {
        "data": {
            "confirmed_params": body.confirmed_params,
            "confirmed_spec": body.confirmed_spec,
            "disclaimer_accepted": body.disclaimer_accepted,
        },
    }
    # Include pipeline config updates for confirm_with_user_node to merge
    if body.pipeline_config_updates:
        resume_data["pipeline_config_updates"] = body.pipeline_config_updates
```

In `pipeline_config.py`, add Deprecation headers:

```python
from fastapi.responses import JSONResponse

@router.get("/tooltips")
async def get_pipeline_tooltips() -> JSONResponse:
    data = {k: v.model_dump() for k, v in get_tooltips().items()}
    return JSONResponse(
        content=data,
        headers={
            "Deprecation": "true",
            "Sunset": "2026-06-01",
            "Link": '</api/v1/pipeline/nodes>; rel="successor-version"',
        },
    )

@router.get("/presets")
async def get_pipeline_presets() -> JSONResponse:
    data = [{"name": k, **v.model_dump()} for k, v in PRESETS.items()]
    return JSONResponse(
        content=data,
        headers={
            "Deprecation": "true",
            "Sunset": "2026-06-01",
            "Link": '</api/v1/pipeline/node-presets>; rel="successor-version"',
        },
    )
```

**Step 4: Run tests — expect PASS**

**Step 5: Commit**

```bash
git commit -m "feat(api): extend ConfirmRequest with pipeline_config_updates + deprecate legacy endpoints"
```

---

### Task 5: 前端类型与 API 对齐

**Files:**
- Modify: `frontend/src/types/pipeline.ts`
- Modify: `frontend/src/services/api.ts`

**Step 1: Add types**

In `frontend/src/types/pipeline.ts`, add:

```typescript
/** Strategy availability per node — GET /pipeline/strategy-availability */
export interface StrategyAvailabilityMap {
  [nodeName: string]: {
    [strategyName: string]: {
      available: boolean;
      reason?: string;
    };
  };
}
```

Update `PipelineNodeDescriptor`:

```typescript
export interface PipelineNodeDescriptor {
  // ... existing fields ...
  fallback_chain?: string[];
}
```

**Step 2: Add API function**

In `frontend/src/services/api.ts`:

```typescript
import type { StrategyAvailabilityMap } from '../types/pipeline.ts';

export async function getStrategyAvailability(): Promise<StrategyAvailabilityMap> {
  const { data } = await api.get<StrategyAvailabilityMap>('/v1/pipeline/strategy-availability');
  return data;
}
```

**Step 3: Verify**

```bash
cd frontend && npx tsc --noEmit && npm run lint
```

**Step 4: Commit**

```bash
git commit -m "feat(frontend): add StrategyAvailability types + API function"
```

---

## Phase 3: 并行前端 (2 Agents)

### Task 6: SchemaForm 组件 [Agent-FE1]

**Files:**
- Create: `frontend/src/components/SchemaForm/index.tsx`

**Implementation:**

```tsx
// frontend/src/components/SchemaForm/index.tsx
import { Switch, Slider, InputNumber, Select, Input, Typography, Divider } from 'antd';

const { Text } = Typography;

interface JsonSchemaProperty {
  type?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  enum?: string[];
  default?: unknown;
  'x-sensitive'?: boolean;
  'x-group'?: string;
}

interface SchemaFormProps {
  schema: {
    properties?: Record<string, JsonSchemaProperty>;
    [key: string]: unknown;
  };
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}

/** Fields handled by NodeConfigCard header — skip in SchemaForm */
const SKIP_FIELDS = new Set(['enabled', 'strategy']);

function renderField(
  name: string,
  prop: JsonSchemaProperty,
  value: unknown,
  onChange: (val: unknown) => void,
) {
  // Sensitive → Password
  if (prop['x-sensitive']) {
    return (
      <Input.Password
        value={value as string ?? prop.default as string ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={prop.description}
        size="small"
      />
    );
  }

  // Boolean → Switch
  if (prop.type === 'boolean') {
    return (
      <Switch
        size="small"
        checked={value as boolean ?? prop.default as boolean ?? false}
        onChange={onChange}
      />
    );
  }

  // Integer/Number with min+max → Slider
  if ((prop.type === 'integer' || prop.type === 'number') &&
      prop.minimum != null && prop.maximum != null) {
    return (
      <Slider
        min={prop.minimum}
        max={prop.maximum}
        value={value as number ?? prop.default as number ?? prop.minimum}
        onChange={onChange}
      />
    );
  }

  // Integer/Number without range → InputNumber
  if (prop.type === 'integer' || prop.type === 'number') {
    return (
      <InputNumber
        size="small"
        value={value as number ?? prop.default as number}
        onChange={(val) => onChange(val)}
        min={prop.minimum}
        max={prop.maximum}
        style={{ width: '100%' }}
      />
    );
  }

  // String with enum → Select
  if (prop.type === 'string' && prop.enum) {
    return (
      <Select
        size="small"
        value={value as string ?? prop.default as string ?? prop.enum[0]}
        onChange={onChange}
        options={prop.enum.map((e) => ({ label: e, value: e }))}
        style={{ width: '100%' }}
      />
    );
  }

  // String without enum → Input
  if (prop.type === 'string') {
    return (
      <Input
        size="small"
        value={value as string ?? prop.default as string ?? ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={prop.description}
      />
    );
  }

  // Unsupported (object, array, etc.) → read-only JSON
  return (
    <Text type="secondary" code style={{ fontSize: 12 }}>
      {JSON.stringify(value ?? prop.default ?? null)}
    </Text>
  );
}

export default function SchemaForm({ schema, value, onChange }: SchemaFormProps) {
  const properties = schema.properties ?? {};

  // Filter and group
  const fields = Object.entries(properties).filter(([name]) => !SKIP_FIELDS.has(name));

  // Group by x-group
  const groups: Record<string, [string, JsonSchemaProperty][]> = {};
  for (const entry of fields) {
    const group = entry[1]['x-group'] ?? '_default';
    if (!groups[group]) groups[group] = [];
    groups[group].push(entry);
  }

  const handleChange = (fieldName: string, fieldValue: unknown) => {
    onChange({ ...value, [fieldName]: fieldValue });
  };

  if (fields.length === 0) return null;

  return (
    <div style={{ padding: '8px 0' }}>
      {Object.entries(groups).map(([group, groupFields]) => (
        <div key={group}>
          {group !== '_default' && (
            <Divider orientation="left" plain style={{ margin: '8px 0', fontSize: 12 }}>
              {group}
            </Divider>
          )}
          {groupFields.map(([name, prop]) => (
            <div key={name} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <Text style={{ fontSize: 12, flex: '0 0 auto' }}>
                  {prop.description ?? name}
                </Text>
                <div style={{ flex: 1, maxWidth: 200 }}>
                  {renderField(name, prop, value[name], (v) => handleChange(name, v))}
                </div>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

**Commit:**

```bash
git commit -m "feat(ui): add SchemaForm component — schema-driven form rendering"
```

---

### Task 7: NodeConfigCard 重构 [Agent-FE2]

**Files:**
- Modify: `frontend/src/components/PipelineConfigBar/CustomPanel.tsx`
- Modify: `frontend/src/components/PipelineConfigBar/index.tsx`

**Implementation:**

Rewrite `CustomPanel.tsx` to use Collapse cards with SchemaForm:

```tsx
// frontend/src/components/PipelineConfigBar/CustomPanel.tsx
import { Switch, Select, Collapse, Tag, Tooltip, Space, Typography } from 'antd';
import SchemaForm from '../SchemaForm/index.tsx';
import type { PipelineNodeDescriptor, NodeLevelConfig, StrategyAvailabilityMap } from '../../types/pipeline.ts';

const { Text } = Typography;

interface CustomPanelProps {
  descriptors: PipelineNodeDescriptor[];
  config: Record<string, NodeLevelConfig>;
  onChange: (nodeConfig: Record<string, NodeLevelConfig>) => void;
  strategyAvailability?: StrategyAvailabilityMap;
}

const NON_TOGGLEABLE = new Set(['create_job', 'confirm_with_user', 'finalize']);

const GROUP_LABELS: Record<string, string> = {
  analysis: '分析',
  generation: '生成',
  postprocess: '后处理',
};

function inferGroup(desc: PipelineNodeDescriptor): string {
  if (desc.is_entry || desc.is_terminal || desc.supports_hitl) return 'system';
  if (desc.name.startsWith('analyze_')) return 'analysis';
  if (desc.name.startsWith('generate_')) return 'generation';
  return 'postprocess';
}

export default function CustomPanel({
  descriptors,
  config,
  onChange,
  strategyAvailability,
}: CustomPanelProps) {
  const groups: Record<string, PipelineNodeDescriptor[]> = {};
  for (const desc of descriptors) {
    const group = inferGroup(desc);
    if (group === 'system') continue;
    if (!groups[group]) groups[group] = [];
    groups[group].push(desc);
  }

  const handleToggle = (nodeName: string, enabled: boolean) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], enabled };
    onChange(updated);
  };

  const handleStrategy = (nodeName: string, strategy: string) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], strategy };
    onChange(updated);
  };

  const handleParams = (nodeName: string, params: Record<string, unknown>) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], ...params };
    onChange(updated);
  };

  const allNodes = Object.entries(groups).flatMap(([group, nodes]) =>
    nodes.map((desc) => {
      const nodeConf = config[desc.name] ?? {};
      const enabled = nodeConf.enabled !== false;
      const canToggle = !NON_TOGGLEABLE.has(desc.name);
      const availability = strategyAvailability?.[desc.name] ?? {};

      return {
        key: desc.name,
        label: (
          <Space size={8}>
            {canToggle && (
              <Switch
                size="small"
                checked={enabled}
                onChange={(val) => { handleToggle(desc.name, val); }}
                onClick={(_, e) => e.stopPropagation()}
              />
            )}
            <Text style={{ opacity: enabled ? 1 : 0.5 }}>
              {desc.display_name}
            </Text>
            {desc.strategies.length > 1 && enabled && (
              <Select
                size="small"
                value={nodeConf.strategy ?? desc.default_strategy ?? desc.strategies[0]}
                onChange={(val) => handleStrategy(desc.name, val)}
                onClick={(e) => e.stopPropagation()}
                options={desc.strategies.map((s) => {
                  const avail = availability[s];
                  const isAvailable = avail?.available !== false;
                  return {
                    label: isAvailable ? s : (
                      <Tooltip title={avail?.reason ?? '不可用'}>
                        <span style={{ opacity: 0.5 }}>{s}</span>
                      </Tooltip>
                    ),
                    value: s,
                    disabled: !isAvailable,
                  };
                })}
                style={{ minWidth: 120 }}
              />
            )}
            {desc.non_fatal && (
              <Tag color="default" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                可选
              </Tag>
            )}
          </Space>
        ),
        children: enabled ? (
          <div>
            {/* Fallback chain */}
            {desc.fallback_chain && desc.fallback_chain.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Text type="secondary" style={{ fontSize: 11 }}>Fallback: </Text>
                {desc.fallback_chain.map((s, i) => (
                  <span key={s}>
                    <Tag color="blue" style={{ fontSize: 11 }}>{s}</Tag>
                    {i < desc.fallback_chain!.length - 1 && <Text type="secondary">→ </Text>}
                  </span>
                ))}
              </div>
            )}
            {/* SchemaForm for dynamic params */}
            {desc.config_schema && (
              <SchemaForm
                schema={desc.config_schema as any}
                value={nodeConf}
                onChange={(params) => handleParams(desc.name, params)}
              />
            )}
          </div>
        ) : null,
        collapsible: enabled ? undefined : ('disabled' as const),
      };
    })
  );

  return (
    <Collapse
      size="small"
      items={allNodes}
      ghost
    />
  );
}
```

Update `index.tsx` to pass `strategyAvailability`:

```tsx
import { getStrategyAvailability } from '../../services/api.ts';
import type { StrategyAvailabilityMap } from '../../types/pipeline.ts';

// Add state:
const [strategyAvailability, setStrategyAvailability] = useState<StrategyAvailabilityMap>({});

// In useEffect:
useEffect(() => {
  // ... existing preset/descriptor fetches ...
  getStrategyAvailability()
    .then(setStrategyAvailability)
    .catch(() => { /* Strategy availability unavailable — no graying out */ });
}, []);

// Pass to CustomPanel:
<CustomPanel
  descriptors={descriptors}
  config={config.nodeConfig}
  onChange={handleCustomChange}
  strategyAvailability={strategyAvailability}
/>
```

**Commit:**

```bash
git commit -m "feat(ui): refactor NodeConfigCard — Collapse cards + SchemaForm + strategy availability"
```

---

## Phase 4: 集成 + ValidationBanner + HITL Dialog (Team Lead)

### Task 8: ValidationBanner

**Files:**
- Create: `frontend/src/components/PipelineConfigBar/ValidationBanner.tsx`
- Modify: `frontend/src/components/PipelineConfigBar/index.tsx`

**Implementation:**

```tsx
// frontend/src/components/PipelineConfigBar/ValidationBanner.tsx
import { useEffect, useRef, useState } from 'react';
import { Alert, Typography } from 'antd';
import { validatePipelineConfig } from '../../services/api.ts';
import type { NodeLevelConfig, PipelineValidateResponse } from '../../types/pipeline.ts';

const { Text } = Typography;

interface ValidationBannerProps {
  config: Record<string, NodeLevelConfig>;
  inputType?: string | null;
}

export default function ValidationBanner({ config, inputType }: ValidationBannerProps) {
  const [result, setResult] = useState<PipelineValidateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    // Clear previous timer
    if (timerRef.current) clearTimeout(timerRef.current);

    // Debounce 300ms
    timerRef.current = setTimeout(() => {
      // Cancel in-flight request
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      validatePipelineConfig(inputType ?? null, config)
        .then((data) => {
          if (!controller.signal.aborted) {
            setResult(data);
          }
        })
        .catch((err) => {
          if (!controller.signal.aborted && err?.name !== 'AbortError') {
            setResult({ valid: false, error: '验证请求失败' });
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [config, inputType]);

  if (!result && !loading) return null;

  if (loading) {
    return <Alert type="info" message="验证中..." showIcon style={{ marginBottom: 8 }} />;
  }

  if (!result) return null;

  if (result.valid) {
    return (
      <Alert
        type="success"
        showIcon
        style={{ marginBottom: 8 }}
        message={
          <Text>
            ✓ 有效 — {result.node_count} 个节点，拓扑: {result.topology?.join(' → ')}
          </Text>
        }
      />
    );
  }

  return (
    <Alert
      type="error"
      showIcon
      style={{ marginBottom: 8 }}
      message={<Text>✗ 无效 — {result.error}</Text>}
    />
  );
}
```

Integrate into `index.tsx` between PresetSelector and CustomPanel.

**Commit:**

```bash
git commit -m "feat(ui): add ValidationBanner with debounce + AbortController"
```

---

### Task 9: HITL ConfirmDialog 扩展

**Files:**
- Modify: `frontend/src/pages/Generate/GenerateWorkflow.tsx`

**Implementation:**

In the confirm functions, add optional `pipelineConfigUpdates` parameter:

```typescript
// In confirmParams() and confirmDrawingSpec():
const confirmDrawingSpec = async (
  spec: DrawingSpec,
  pipelineConfigUpdates?: Record<string, Record<string, unknown>>,
) => {
  // ... existing logic ...
  const body: any = {
    confirmed_spec: spec,
    disclaimer_accepted: true,
  };
  if (pipelineConfigUpdates) {
    body.pipeline_config_updates = pipelineConfigUpdates;
  }
  // ... fetch call with body ...
};
```

Add collapsible "高级配置" section in the confirm dialog JSX (uses NodeConfigCard for unexecuted nodes).

**Commit:**

```bash
git commit -m "feat(ui): extend HITL ConfirmDialog with pipeline config editing"
```

---

## Phase 5: E2E 测试 (Team Lead)

### Task 10: E2E Tests

**Files:**
- Create: `frontend/e2e/pipeline-config.spec.ts`

**Implementation:**

```typescript
// frontend/e2e/pipeline-config.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Pipeline Configuration', () => {

  test('disabled node excluded from validate topology', async ({ page }) => {
    // Mock validate API
    await page.route('**/api/v1/pipeline/validate', async (route) => {
      const body = JSON.parse(route.request().postData() ?? '{}');
      const config = body.config ?? {};
      // Check if mesh_repair is disabled
      const meshRepairDisabled = config.mesh_repair?.enabled === false;
      await route.fulfill({
        json: {
          valid: true,
          node_count: meshRepairDisabled ? 3 : 4,
          topology: meshRepairDisabled
            ? ['analyze', 'generate', 'finalize']
            : ['analyze', 'generate', 'mesh_repair', 'finalize'],
        },
      });
    });

    await page.goto('/');
    // ... interact with pipeline config UI, disable mesh_repair
    // ... verify ValidationBanner shows topology without mesh_repair
  });

  test('all nodes disabled shows invalid banner', async ({ page }) => {
    await page.route('**/api/v1/pipeline/validate', async (route) => {
      await route.fulfill({
        json: { valid: false, error: '至少需要启用一个节点', node_count: 0 },
      });
    });

    await page.goto('/');
    // ... disable all toggleable nodes
    // ... verify red "无效" banner appears
  });

  test('strategy unavailable shows disabled option with tooltip', async ({ page }) => {
    await page.route('**/api/v1/pipeline/strategy-availability', async (route) => {
      await route.fulfill({
        json: {
          generate_raw_mesh: {
            hunyuan3d: { available: false, reason: 'API Key 未配置' },
            tripo3d: { available: true },
          },
        },
      });
    });

    await page.goto('/');
    // ... open node config, verify hunyuan3d option disabled
    // ... hover and verify tooltip shows "API Key 未配置"
  });

  test('HITL config change included in confirm request', async ({ page }) => {
    let confirmBody: any;
    await page.route('**/api/v1/jobs/*/confirm', async (route) => {
      confirmBody = JSON.parse(route.request().postData() ?? '{}');
      await route.fulfill({ json: { status: 'ok' } });
    });

    // ... trigger HITL flow, change strategy in dialog, confirm
    // ... verify confirmBody.pipeline_config_updates contains the change
  });

  test('custom params passed through to job creation', async ({ page }) => {
    await page.route('**/api/v1/pipeline/nodes', async (route) => {
      await route.fulfill({
        json: {
          nodes: [{
            name: 'mesh_repair',
            display_name: '网格修复',
            requires: ['raw_mesh'],
            produces: ['repaired_mesh'],
            input_types: ['organic'],
            strategies: ['manifold', 'trimesh'],
            default_strategy: 'manifold',
            is_entry: false,
            is_terminal: false,
            supports_hitl: false,
            non_fatal: false,
            description: '修复网格',
            config_schema: {
              properties: {
                enabled: { type: 'boolean' },
                strategy: { type: 'string' },
                timeout: {
                  type: 'integer',
                  minimum: 10,
                  maximum: 600,
                  description: '超时时间（秒）',
                },
              },
            },
          }],
        },
      });
    });

    await page.goto('/');
    // ... expand node config, change timeout via Slider
    // ... verify validate call includes the custom timeout value
  });
});
```

**Commit:**

```bash
git commit -m "test(e2e): add pipeline config E2E tests"
```

---

## Phase 6: Review Team

审查维度：
- Codex 代码审查
- Gemini 代码审查 + UI 审查
- 测试覆盖分析

按 dev-workflow 的 Review Team 结构执行。

---

## 验证清单

```bash
# 后端
uv run pytest tests/ -v

# 前端
cd frontend && npx tsc --noEmit && npm run lint

# E2E
cd frontend && npx playwright test e2e/pipeline-config.spec.ts
```
