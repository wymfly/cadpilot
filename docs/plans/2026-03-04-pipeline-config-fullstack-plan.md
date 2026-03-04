# Pipeline Config Fullstack Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 补全管线配置的全栈能力——运行时节点跳过、策略可用性 API、Schema 驱动前端表单引擎、HITL 中调参、e2e 验证。

**Architecture:** 后端 `_wrap_node()` 增加 enabled 检查实现运行时跳过；`registry.py` 增强 config_schema 生成（description/min/max/x-group/x-sensitive）；前端 `SchemaForm` 组件根据 JSON Schema 动态渲染 Ant Design 控件；`ValidationBanner` debounce 调用 validate API；confirm 端点扩展 `pipeline_config_updates` 支持 HITL 中调参。

**Tech Stack:** Python 3.10+ / FastAPI / LangGraph / Pydantic v2 / React / Ant Design / TypeScript

**Design doc:** `docs/plans/2026-03-04-pipeline-config-fullstack-design.md`
**OpenSpec:** `openspec/changes/pipeline-config-fullstack/`

---

## 并行感知：执行拓扑

```
T1(串行: 后端运行时跳过) → T2(串行: 策略可用性 API) → T3(串行: schema 增强)
→ T4(串行: confirm 扩展 + 旧 API 废弃)
→ [T5 || T6](并行: 前端 SchemaForm || 前端类型+API)
→ T7(串行: NodeConfigCard 重构，依赖 T5+T6)
→ T8(串行: ValidationBanner)
→ T9(串行: HITL ConfirmDialog 扩展)
→ T10(串行: E2E 测试)
```

### 文件交叉矩阵

| Task | 修改文件 |
|------|---------|
| T1 | `backend/graph/builder.py`, `backend/graph/resolver.py`, `tests/test_graph_builder.py`(新) |
| T2 | `backend/api/v1/pipeline_config.py`, `tests/test_pipeline_config_api.py`(新) |
| T3 | `backend/graph/registry.py`, `tests/test_registry_schema.py`(新) |
| T4 | `backend/api/v1/jobs.py`, `backend/api/v1/pipeline_config.py`, `tests/test_api_v1.py` |
| T5 | `frontend/src/components/SchemaForm/index.tsx`(新) |
| T6 | `frontend/src/types/pipeline.ts`, `frontend/src/services/api.ts` |
| T7 | `frontend/src/components/PipelineConfigBar/CustomPanel.tsx`, `frontend/src/components/PipelineConfigBar/index.tsx` |
| T8 | `frontend/src/components/PipelineConfigBar/ValidationBanner.tsx`(新), `frontend/src/components/PipelineConfigBar/index.tsx` |
| T9 | `frontend/src/pages/Generate/GenerateWorkflow.tsx`, `frontend/src/components/PipelineConfigBar/index.tsx` |
| T10 | `tests/e2e/test_pipeline_config_e2e.py`(新) |

**并行安全**: T5 和 T6 修改文件集无交叉，可安全并行。

---

### Task 1: 后端运行时节点跳过

**Files:**
- Modify: `backend/graph/builder.py:108-180` — `_wrap_node()` 增加 enabled 检查
- Modify: `backend/graph/resolver.py:64-72` — 移除编译时 enabled 过滤
- Create: `tests/test_graph_builder.py` — 运行时跳过测试

**Step 1: Write the failing test for runtime skip**

```python
# tests/test_graph_builder.py
"""Tests for GraphBuilder — runtime node skip."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


def test_wrap_node_skips_disabled():
    """_wrap_node() should return {} when node is disabled in pipeline_config."""
    from backend.graph.builder import GraphBuilder
    from backend.graph.descriptor import NodeDescriptor

    desc = NodeDescriptor(
        name="test_node",
        display_name="Test",
        fn=AsyncMock(),
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

    builder = GraphBuilder.__new__(GraphBuilder)
    wrapped = builder._wrap_node(desc)

    # State with node disabled
    state = {
        "job_id": "test-job",
        "pipeline_config": {"test_node": {"enabled": False}},
    }

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(wrapped(state))
    assert result == {}
    desc.fn.assert_not_called()


def test_wrap_node_executes_when_enabled():
    """_wrap_node() should execute normally when node is enabled."""
    from backend.graph.builder import GraphBuilder
    from backend.graph.descriptor import NodeDescriptor
    from backend.graph.context import NodeContext

    mock_fn = AsyncMock(return_value={"some_key": "value"})
    desc = NodeDescriptor(
        name="test_node",
        display_name="Test",
        fn=mock_fn,
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

    builder = GraphBuilder.__new__(GraphBuilder)
    wrapped = builder._wrap_node(desc)

    state = {
        "job_id": "test-job",
        "pipeline_config": {"test_node": {"enabled": True}},
    }

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(wrapped(state))
    assert result != {}
    mock_fn.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: FAIL — `_wrap_node()` doesn't check enabled yet

**Step 3: Implement runtime skip in `_wrap_node()`**

In `backend/graph/builder.py`, at line 111 (inside `async def wrapped(state)`), add the enabled check **before** any other logic:

```python
    async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        # Runtime skip: check if node is disabled in pipeline_config
        node_cfg = state.get("pipeline_config", {}).get(desc.name, {})
        if not node_cfg.get("enabled", True):
            logger.info("Node %s skipped (disabled)", desc.name)
            return {}

        job_id = state.get("job_id", "unknown")
        t0 = time.time()
        # ... rest of existing logic unchanged
```

**Step 4: Write the failing test for resolver**

Add to `tests/test_graph_builder.py`:

```python
def test_resolver_includes_disabled_nodes():
    """resolve_all() should NOT filter out disabled nodes anymore."""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry
    from backend.graph.resolver import DependencyResolver

    discover_nodes()

    # Get all node names with no config (all enabled)
    resolved_all = DependencyResolver.resolve(registry, {}, None)
    all_names = {d.name for d in resolved_all.ordered_nodes}

    # Now disable one node — it should still appear
    first_disableable = None
    for d in resolved_all.ordered_nodes:
        if not d.is_entry and not d.is_terminal and not d.supports_hitl:
            first_disableable = d.name
            break

    if first_disableable:
        config = {first_disableable: {"enabled": False}}
        resolved_disabled = DependencyResolver.resolve(registry, config, None)
        disabled_names = {d.name for d in resolved_disabled.ordered_nodes}
        assert first_disableable in disabled_names
```

**Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_graph_builder.py::test_resolver_includes_disabled_nodes -v`
Expected: FAIL — resolver currently filters out disabled nodes

**Step 6: Remove compile-time enabled filter from resolver**

In `backend/graph/resolver.py:64-72`, remove the enabled check but keep input_type filtering:

```python
        # Step 1: filter by input_type (enabled filtering moved to runtime)
        candidates: dict[str, NodeDescriptor] = {}
        for name, desc in all_nodes.items():
            if input_type and input_type not in desc.input_types:
                continue
            candidates[name] = desc
```

**Step 7: Run all tests to verify**

Run: `uv run pytest tests/test_graph_builder.py tests/ -v`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add backend/graph/builder.py backend/graph/resolver.py tests/test_graph_builder.py
git commit -m "feat: runtime node skip — replace compile-time enabled filtering"
```

---

### Task 2: 后端策略可用性 API

**Files:**
- Modify: `backend/api/v1/pipeline_config.py:11-105` — 新增端点
- Create: `tests/test_pipeline_config_api.py` — API 测试

**Step 1: Write the failing test**

```python
# tests/test_pipeline_config_api.py
"""Tests for pipeline config API — strategy-availability endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.main import app
    return TestClient(app)


def test_strategy_availability_returns_status(client: TestClient):
    """GET /pipeline/strategy-availability returns availability per node per strategy."""
    resp = client.get("/api/v1/pipeline/strategy-availability")
    assert resp.status_code == 200
    data = resp.json()
    # Should be a dict of {node_name: {strategy_name: {available: bool}}}
    assert isinstance(data, dict)
    for node_name, strategies in data.items():
        assert isinstance(strategies, dict)
        for strat_name, status in strategies.items():
            assert "available" in status


def test_strategy_availability_unavailable_has_reason(client: TestClient):
    """Unavailable strategies should include a reason."""
    resp = client.get("/api/v1/pipeline/strategy-availability")
    data = resp.json()
    for node_name, strategies in data.items():
        for strat_name, status in strategies.items():
            if not status["available"]:
                assert "reason" in status
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline_config_api.py -v`
Expected: FAIL — 404, endpoint doesn't exist

**Step 3: Implement the endpoint**

In `backend/api/v1/pipeline_config.py`, add after the existing endpoints:

```python
@router.get("/strategy-availability")
async def get_strategy_availability() -> dict[str, Any]:
    """返回每个节点每个策略的可用性状态。"""
    from backend.graph.discovery import discover_nodes
    from backend.graph.registry import registry
    from backend.graph.descriptor import BaseNodeConfig

    discover_nodes()

    result: dict[str, Any] = {}
    for name, desc in registry.all().items():
        if not desc.strategies:
            continue
        avail: dict[str, Any] = {}
        for s_name, s_cls in desc.strategies.items():
            try:
                config = desc.config_model() if desc.config_model else BaseNodeConfig()
                instance = s_cls(config=config)
                available = instance.check_available()
                avail[s_name] = {"available": available}
                if not available:
                    avail[s_name]["reason"] = getattr(
                        instance, "unavailable_reason", "依赖未满足"
                    )
            except Exception as exc:
                avail[s_name] = {"available": False, "reason": str(exc)}
        result[name] = avail
    return result
```

Also add `BaseNodeConfig` import. Check if `BaseNodeConfig` exists in descriptor:

```python
# At top of pipeline_config.py, the existing imports are sufficient.
# BaseNodeConfig import will be inside the function body.
```

**Step 4: Run tests to verify**

Run: `uv run pytest tests/test_pipeline_config_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/api/v1/pipeline_config.py tests/test_pipeline_config_api.py
git commit -m "feat: add GET /pipeline/strategy-availability endpoint"
```

---

### Task 3: 后端 config_schema 增强

**Files:**
- Modify: `backend/graph/registry.py:82-143` — 增强 schema 后处理
- Modify: `backend/api/v1/pipeline_config.py:24-52` — schema 增强应用
- Create: `tests/test_registry_schema.py` — Schema 生成测试

**Step 1: Write the failing test**

```python
# tests/test_registry_schema.py
"""Tests for enhanced config_schema generation."""

from __future__ import annotations

from pydantic import BaseModel, Field


def test_schema_has_description():
    """Fields with description should appear in schema."""
    class TestConfig(BaseModel):
        timeout: int = Field(default=60, description="超时时间（秒）")

    schema = TestConfig.model_json_schema()
    assert schema["properties"]["timeout"]["description"] == "超时时间（秒）"


def test_schema_has_min_max():
    """Fields with ge/le should produce minimum/maximum in schema."""
    class TestConfig(BaseModel):
        timeout: int = Field(default=60, ge=10, le=600)

    schema = TestConfig.model_json_schema()
    assert schema["properties"]["timeout"]["minimum"] == 10
    assert schema["properties"]["timeout"]["maximum"] == 600


def test_schema_has_x_group():
    """Fields with x-group in json_schema_extra should appear in schema."""
    class TestConfig(BaseModel):
        timeout: int = Field(default=60, json_schema_extra={"x-group": "高级"})

    schema = TestConfig.model_json_schema()
    assert schema["properties"]["timeout"]["x-group"] == "高级"


def test_schema_sensitive_field_auto_detected():
    """Fields named api_key/secret/password should get x-sensitive."""
    from backend.graph.registry import enhance_config_schema

    class TestConfig(BaseModel):
        api_key: str = Field(default="")
        secret_token: str = Field(default="")
        password: str = Field(default="")
        timeout: int = Field(default=60)

    schema = TestConfig.model_json_schema()
    enhanced = enhance_config_schema(schema)
    assert enhanced["properties"]["api_key"].get("x-sensitive") is True
    assert enhanced["properties"]["secret_token"].get("x-sensitive") is True
    assert enhanced["properties"]["password"].get("x-sensitive") is True
    assert enhanced["properties"]["timeout"].get("x-sensitive") is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry_schema.py -v`
Expected: FAIL — `enhance_config_schema` doesn't exist

**Step 3: Implement `enhance_config_schema()` in registry.py**

Add at the end of `backend/graph/registry.py` (after line 143):

```python
def enhance_config_schema(schema: dict) -> dict:
    """Post-process Pydantic JSON schema to add x-sensitive for sensitive fields.

    Pydantic already handles description, minimum/maximum, x-group via
    json_schema_extra — this function only adds auto-detection for
    sensitive field names.
    """
    SENSITIVE_PATTERNS = ("api_key", "secret", "password")
    props = schema.get("properties", {})
    for field_name, field_schema in props.items():
        if any(pattern in field_name for pattern in SENSITIVE_PATTERNS):
            field_schema["x-sensitive"] = True
    return schema
```

**Step 4: Apply `enhance_config_schema` in the `/nodes` endpoint**

In `backend/api/v1/pipeline_config.py:48-50`, modify the schema emission:

```python
        # Add config JSON schema if available
        if desc.config_model:
            from backend.graph.registry import enhance_config_schema
            node_info["config_schema"] = enhance_config_schema(
                desc.config_model.model_json_schema()
            )
```

**Step 5: Run tests**

Run: `uv run pytest tests/test_registry_schema.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add backend/graph/registry.py backend/api/v1/pipeline_config.py tests/test_registry_schema.py
git commit -m "feat: enhance config_schema with x-sensitive auto-detection"
```

---

### Task 4: 后端 confirm 端点扩展 + 旧 API 废弃

**Files:**
- Modify: `backend/api/v1/jobs.py:113-120` — ConfirmRequest 扩展
- Modify: `backend/api/v1/jobs.py:640-654` — deep-merge 逻辑
- Modify: `backend/api/v1/pipeline_config.py:14-21` — Deprecated headers
- Modify: `tests/test_api_v1.py` — 新增 confirm config merge 测试

**Step 1: Write the failing test**

Add to `tests/test_api_v1.py`, in the `TestConfirmJob` class:

```python
    def test_confirm_with_pipeline_config_updates(self, client: TestClient) -> None:
        """confirm with pipeline_config_updates should be accepted."""
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "test"},
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)

        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={
                "confirmed_params": {"diameter": 100.0},
                "pipeline_config_updates": {
                    "mesh_repair": {"strategy": "trimesh", "timeout": 300},
                },
            },
        )
        assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_v1.py::TestConfirmJob::test_confirm_with_pipeline_config_updates -v`
Expected: FAIL — `pipeline_config_updates` is unknown field (Pydantic validation error)

**Step 3: Extend ConfirmRequest**

In `backend/api/v1/jobs.py:113-120`:

```python
class ConfirmRequest(BaseModel):
    """HITL 参数确认请求（统一文本和图纸模式）。"""

    confirmed_params: dict[str, float] = Field(default_factory=dict)
    confirmed_spec: dict[str, Any] | None = None
    base_body_method: str = "extrude"
    disclaimer_accepted: bool = True
    pipeline_config_updates: dict[str, dict] | None = None
```

**Step 4: Add deep-merge logic before resume**

In `backend/api/v1/jobs.py`, after line 654 (after `resume_data` is built, before `event_stream()`):

```python
    # Deep-merge pipeline_config_updates into graph state
    if body.pipeline_config_updates:
        resume_data["data"]["pipeline_config_updates"] = body.pipeline_config_updates
```

Then in the confirm_with_user node (or at graph resume), the updates need to be merged. Since `Command(resume=resume_data)` passes the data to the interrupted node which reads it, we need to handle the merge in the `confirm_with_user` node. However, for now we pass it through `resume_data` and let the confirm node handle it:

Actually, the merge should happen on the graph state's `pipeline_config` before execution continues. The cleanest approach is to update the checkpoint state:

```python
    # Deep-merge pipeline_config_updates into graph state before resume
    if body.pipeline_config_updates:
        # Get current graph state
        graph_state = await cad_graph.aget_state(config)
        current_pc = dict(graph_state.values.get("pipeline_config") or {})
        for node_name, updates in body.pipeline_config_updates.items():
            current_pc.setdefault(node_name, {}).update(updates)
        # Update state with merged config
        await cad_graph.aupdate_state(
            config,
            {"pipeline_config": current_pc},
        )
```

Place this code at `jobs.py` line 654, right after building `resume_data` and before defining `event_stream()`.

**Step 5: Add Deprecated headers to old APIs**

In `backend/api/v1/pipeline_config.py`, modify the tooltips and presets endpoints:

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

**Step 6: Run all tests**

Run: `uv run pytest tests/test_api_v1.py tests/test_pipeline_config.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add backend/api/v1/jobs.py backend/api/v1/pipeline_config.py tests/test_api_v1.py
git commit -m "feat: extend confirm endpoint with pipeline_config_updates + deprecate old APIs"
```

---

### Task 5: 前端 SchemaForm 组件 (可与 T6 并行)

**Files:**
- Create: `frontend/src/components/SchemaForm/index.tsx`

**Step 1: Create SchemaForm component**

```tsx
// frontend/src/components/SchemaForm/index.tsx
import { Switch, InputNumber, Slider, Select, Input, Typography, Space } from 'antd';

const { Text } = Typography;

interface JSONSchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  'x-group'?: string;
  'x-sensitive'?: boolean;
}

interface JSONSchema {
  properties?: Record<string, JSONSchemaProperty>;
  required?: string[];
}

interface SchemaFormProps {
  schema: JSONSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
}

/** Fields handled by NodeConfigCard header — skip in SchemaForm */
const SKIP_FIELDS = new Set(['enabled', 'strategy']);

function renderControl(
  fieldName: string,
  prop: JSONSchemaProperty,
  currentValue: unknown,
  onFieldChange: (name: string, val: unknown) => void,
) {
  if (prop['x-sensitive']) {
    return (
      <Input.Password
        size="small"
        value={(currentValue as string) ?? prop.default ?? ''}
        onChange={(e) => onFieldChange(fieldName, e.target.value)}
        style={{ width: '100%' }}
      />
    );
  }

  if (prop.type === 'boolean') {
    return (
      <Switch
        size="small"
        checked={(currentValue as boolean) ?? (prop.default as boolean) ?? false}
        onChange={(val) => onFieldChange(fieldName, val)}
      />
    );
  }

  if ((prop.type === 'integer' || prop.type === 'number') && prop.minimum != null && prop.maximum != null) {
    return (
      <Slider
        min={prop.minimum}
        max={prop.maximum}
        value={(currentValue as number) ?? (prop.default as number) ?? prop.minimum}
        onChange={(val) => onFieldChange(fieldName, val)}
        style={{ width: '100%' }}
      />
    );
  }

  if (prop.type === 'integer' || prop.type === 'number') {
    return (
      <InputNumber
        size="small"
        value={(currentValue as number) ?? (prop.default as number)}
        min={prop.minimum}
        max={prop.maximum}
        onChange={(val) => onFieldChange(fieldName, val)}
        style={{ width: '100%' }}
      />
    );
  }

  if (prop.type === 'string' && prop.enum) {
    return (
      <Select
        size="small"
        value={(currentValue as string) ?? (prop.default as string) ?? prop.enum[0]}
        options={prop.enum.map((e) => ({ label: e, value: e }))}
        onChange={(val) => onFieldChange(fieldName, val)}
        style={{ width: '100%' }}
      />
    );
  }

  // Default: text input
  return (
    <Input
      size="small"
      value={(currentValue as string) ?? (prop.default as string) ?? ''}
      onChange={(e) => onFieldChange(fieldName, e.target.value)}
      style={{ width: '100%' }}
    />
  );
}

export default function SchemaForm({ schema, value, onChange }: SchemaFormProps) {
  const properties = schema.properties ?? {};

  // Filter out skip fields
  const fields = Object.entries(properties).filter(
    ([name]) => !SKIP_FIELDS.has(name),
  );

  if (fields.length === 0) return null;

  // Group by x-group
  const groups: Record<string, [string, JSONSchemaProperty][]> = {};
  for (const entry of fields) {
    const group = entry[1]['x-group'] ?? '基本';
    if (!groups[group]) groups[group] = [];
    groups[group].push(entry);
  }

  const handleFieldChange = (fieldName: string, val: unknown) => {
    onChange({ ...value, [fieldName]: val });
  };

  return (
    <div style={{ padding: '8px 0' }}>
      {Object.entries(groups).map(([group, groupFields]) => (
        <div key={group} style={{ marginBottom: 12 }}>
          {Object.keys(groups).length > 1 && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              {group}
            </Text>
          )}
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {groupFields.map(([name, prop]) => (
              <div
                key={name}
                style={{ display: 'flex', alignItems: 'center', gap: 8 }}
              >
                <Text style={{ minWidth: 100, fontSize: 12 }}>
                  {prop.description ?? name}
                </Text>
                <div style={{ flex: 1 }}>
                  {renderControl(name, prop, value[name], handleFieldChange)}
                </div>
              </div>
            ))}
          </Space>
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS (no type errors)

**Step 3: Commit**

```bash
git add frontend/src/components/SchemaForm/index.tsx
git commit -m "feat: add SchemaForm component — Schema-driven dynamic form rendering"
```

---

### Task 6: 前端类型与 API 对齐 (可与 T5 并行)

**Files:**
- Modify: `frontend/src/types/pipeline.ts:48-89` — 新增 StrategyAvailability 类型
- Modify: `frontend/src/services/api.ts` — 新增 API 函数

**Step 1: Add StrategyAvailability types**

In `frontend/src/types/pipeline.ts`, add after `PipelineValidateResponse` (line 89):

```typescript
/** Strategy availability status for a single strategy */
export interface StrategyStatus {
  available: boolean;
  reason?: string;
}

/** Strategy availability response from GET /pipeline/strategy-availability */
export type StrategyAvailabilityMap = Record<string, Record<string, StrategyStatus>>;
```

Also add `fallback_chain` to `PipelineNodeDescriptor` (currently missing):

```typescript
export interface PipelineNodeDescriptor {
  name: string;
  display_name: string;
  requires: (string | string[])[];
  produces: string[];
  input_types: string[];
  strategies: string[];
  default_strategy: string | null;
  fallback_chain?: string[];  // NEW
  is_entry: boolean;
  is_terminal: boolean;
  supports_hitl: boolean;
  non_fatal: boolean;
  description: string | null;
  config_schema?: Record<string, unknown>;
}
```

**Step 2: Add API function**

In `frontend/src/services/api.ts`, add:

```typescript
import type { StrategyAvailabilityMap } from '../types/pipeline.ts';

export async function getStrategyAvailability(): Promise<StrategyAvailabilityMap> {
  const { data } = await api.get<StrategyAvailabilityMap>('/v1/pipeline/strategy-availability');
  return data;
}
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/types/pipeline.ts frontend/src/services/api.ts
git commit -m "feat: add StrategyAvailability types and API function"
```

---

### Task 7: 前端 NodeConfigCard 重构

**Files:**
- Modify: `frontend/src/components/PipelineConfigBar/CustomPanel.tsx` — 重构为卡片式
- Modify: `frontend/src/components/PipelineConfigBar/index.tsx` — 集成策略可用性

**Step 1: Refactor CustomPanel to card-based layout**

Rewrite `frontend/src/components/PipelineConfigBar/CustomPanel.tsx`:

```tsx
import { Switch, Select, Collapse, Tag, Tooltip, Space, Typography } from 'antd';
import { useDesignTokens } from '../../theme/useDesignTokens.ts';
import SchemaForm from '../SchemaForm/index.tsx';
import type {
  PipelineNodeDescriptor,
  NodeLevelConfig,
  StrategyAvailabilityMap,
  StrategyStatus,
} from '../../types/pipeline.ts';

const { Text } = Typography;

interface CustomPanelProps {
  descriptors: PipelineNodeDescriptor[];
  config: Record<string, NodeLevelConfig>;
  onChange: (nodeConfig: Record<string, NodeLevelConfig>) => void;
  strategyAvailability?: StrategyAvailabilityMap;
}

/** Nodes that are always enabled and cannot be toggled */
const NON_TOGGLEABLE = new Set(['create_job', 'confirm_with_user', 'finalize']);

/** Group label mapping */
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
  const dt = useDesignTokens();

  // Group configurable nodes
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

  const handleParamChange = (nodeName: string, params: Record<string, unknown>) => {
    const updated = { ...config };
    updated[nodeName] = { ...updated[nodeName], ...params };
    onChange(updated);
  };

  const allNodes = Object.values(groups).flat();

  const collapseItems = allNodes.map((desc) => {
    const nodeConf = config[desc.name] ?? {};
    const enabled = nodeConf.enabled !== false;
    const canToggle = !NON_TOGGLEABLE.has(desc.name);
    const nodeAvail = strategyAvailability?.[desc.name] ?? {};

    const strategyOptions = desc.strategies.map((s) => {
      const status: StrategyStatus | undefined = nodeAvail[s];
      const isAvailable = status?.available !== false;
      return {
        label: isAvailable ? s : (
          <Tooltip title={status?.reason ?? '不可用'}>{s}</Tooltip>
        ),
        value: s,
        disabled: !isAvailable,
      };
    });

    const header = (
      <Space size={8} style={{ width: '100%' }}>
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
        {desc.non_fatal && (
          <Tag color="default" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
            可选
          </Tag>
        )}
        {desc.strategies.length > 1 && enabled && (
          <Select
            size="small"
            value={nodeConf.strategy ?? desc.default_strategy ?? desc.strategies[0]}
            onChange={(val) => handleStrategy(desc.name, val)}
            options={strategyOptions}
            style={{ minWidth: 120 }}
            onClick={(e) => e.stopPropagation()}
          />
        )}
      </Space>
    );

    return {
      key: desc.name,
      label: header,
      children: (
        <div>
          {desc.config_schema && (
            <SchemaForm
              schema={desc.config_schema as any}
              value={nodeConf}
              onChange={(params) => handleParamChange(desc.name, params)}
            />
          )}
          {desc.fallback_chain && desc.fallback_chain.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12, marginRight: 8 }}>
                Fallback:
              </Text>
              {desc.fallback_chain.map((name, i) => (
                <Tag key={name} color="blue" style={{ fontSize: 11 }}>
                  {i > 0 ? '→ ' : ''}{name}
                </Tag>
              ))}
            </div>
          )}
        </div>
      ),
    };
  });

  return (
    <Collapse
      size="small"
      items={collapseItems}
      ghost
    />
  );
}
```

**Step 2: Update PipelineConfigBar to fetch strategy availability**

In `frontend/src/components/PipelineConfigBar/index.tsx`, add:

```tsx
import { getStrategyAvailability } from '../../services/api.ts';
import type { StrategyAvailabilityMap } from '../../types/pipeline.ts';

// Inside PipelineConfigBar component, add state:
const [stratAvail, setStratAvail] = useState<StrategyAvailabilityMap>({});

// In the useEffect:
useEffect(() => {
  getNodePresets()
    .then(setPresets)
    .catch(() => {});
  getPipelineNodes()
    .then(setDescriptors)
    .catch(() => {});
  getStrategyAvailability()
    .then(setStratAvail)
    .catch(() => {});
}, []);

// Pass to CustomPanel:
<CustomPanel
  descriptors={descriptors}
  config={config.nodeConfig}
  onChange={handleCustomChange}
  strategyAvailability={stratAvail}
/>
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/components/PipelineConfigBar/CustomPanel.tsx frontend/src/components/PipelineConfigBar/index.tsx
git commit -m "feat: refactor CustomPanel to card-based layout with SchemaForm + strategy availability"
```

---

### Task 8: 前端 ValidationBanner

**Files:**
- Create: `frontend/src/components/PipelineConfigBar/ValidationBanner.tsx`
- Modify: `frontend/src/components/PipelineConfigBar/index.tsx` — 集成

**Step 1: Create ValidationBanner component**

```tsx
// frontend/src/components/PipelineConfigBar/ValidationBanner.tsx
import { useEffect, useState, useRef } from 'react';
import { Alert } from 'antd';
import { validatePipelineConfig } from '../../services/api.ts';
import type { NodeLevelConfig, PipelineValidateResponse } from '../../types/pipeline.ts';

interface ValidationBannerProps {
  config: Record<string, NodeLevelConfig>;
  inputType?: string;
}

export default function ValidationBanner({ config, inputType }: ValidationBannerProps) {
  const [result, setResult] = useState<PipelineValidateResponse | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    timerRef.current = setTimeout(() => {
      validatePipelineConfig(inputType ?? null, config)
        .then(setResult)
        .catch(() => setResult(null));
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [config, inputType]);

  if (!result) return null;

  if (result.valid) {
    return (
      <Alert
        type="success"
        showIcon
        message={`有效 — ${result.node_count} 个节点`}
        description={result.topology?.join(' → ')}
        style={{ marginBottom: 8 }}
        banner
      />
    );
  }

  return (
    <Alert
      type="error"
      showIcon
      message="配置无效"
      description={result.error}
      style={{ marginBottom: 8 }}
      banner
    />
  );
}
```

**Step 2: Integrate into PipelineConfigBar**

In `frontend/src/components/PipelineConfigBar/index.tsx`, add:

```tsx
import ValidationBanner from './ValidationBanner.tsx';

// Inside JSX, between PresetSelector and Collapse:
<ValidationBanner config={config.nodeConfig} />
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 4: Commit**

```bash
git add frontend/src/components/PipelineConfigBar/ValidationBanner.tsx frontend/src/components/PipelineConfigBar/index.tsx
git commit -m "feat: add ValidationBanner — real-time pipeline config validation"
```

---

### Task 9: 前端 HITL ConfirmDialog 扩展

**Files:**
- Modify: `frontend/src/pages/Generate/GenerateWorkflow.tsx:164-190, 255-277` — confirm 请求中包含 pipeline_config_updates

**Step 1: Extend confirmParams to accept pipeline_config_updates**

In `frontend/src/pages/Generate/GenerateWorkflow.tsx`, the `confirmParams` and `confirmDrawingSpec` callbacks make fetch calls to `/api/v1/jobs/{id}/confirm`. We need to pass `pipeline_config_updates` alongside existing params.

First, update the type signature in `GenerateWorkflowContext.tsx`:

```tsx
// In GenerateWorkflowContextValue interface:
confirmParams: (
  params: Record<string, number>,
  pipelineConfigUpdates?: Record<string, Record<string, unknown>>,
) => Promise<void>;
confirmDrawingSpec: (
  spec: DrawingSpec,
  disclaimerAccepted: boolean,
  pipelineConfigUpdates?: Record<string, Record<string, unknown>>,
) => Promise<void>;
```

Then in `GenerateWorkflow.tsx`, update the callbacks:

```tsx
const confirmParams = useCallback(
  async (
    confirmedParams: Record<string, number>,
    pipelineConfigUpdates?: Record<string, Record<string, unknown>>,
  ) => {
    // ... existing logic ...
    const bodyData: Record<string, unknown> = { confirmed_params: confirmedParams };
    if (pipelineConfigUpdates) {
      bodyData.pipeline_config_updates = pipelineConfigUpdates;
    }
    const resp = await fetch(`/api/v1/jobs/${state.jobId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyData),
      signal: abort.signal,
    });
    // ... rest unchanged
```

Similarly for `confirmDrawingSpec`:

```tsx
const confirmDrawingSpec = useCallback(
  async (
    confirmedSpec: DrawingSpec,
    disclaimerAccepted: boolean,
    pipelineConfigUpdates?: Record<string, Record<string, unknown>>,
  ) => {
    // ... existing logic ...
    const bodyData: Record<string, unknown> = {
      confirmed_spec: confirmedSpec,
      disclaimer_accepted: disclaimerAccepted,
    };
    if (pipelineConfigUpdates) {
      bodyData.pipeline_config_updates = pipelineConfigUpdates;
    }
    const resp = await fetch(`/api/v1/jobs/${state.jobId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyData),
      signal: abort.signal,
    });
    // ... rest unchanged
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 3: Commit**

```bash
git add frontend/src/pages/Generate/GenerateWorkflow.tsx frontend/src/contexts/GenerateWorkflowContext.tsx
git commit -m "feat: extend confirm callbacks to pass pipeline_config_updates"
```

---

### Task 10: E2E 测试

**Files:**
- Create: `tests/e2e/test_pipeline_config_e2e.py`

**Step 1: Write E2E tests**

```python
# tests/e2e/test_pipeline_config_e2e.py
"""E2E tests for pipeline config fullstack feature.

Covers:
- Preset selection → Job creation
- Node disable → validate warning
- Custom params → Job reads modified params
- HITL confirm with pipeline_config_updates
"""

from __future__ import annotations

import json
from tests.e2e.conftest import get_sse_job_id, parse_sse_events

import pytest
from fastapi.testclient import TestClient


class TestPipelineConfigE2E:
    def test_preset_creates_job(self, client: TestClient) -> None:
        """Creating a Job with a preset config should work via SSE."""
        resp = client.post(
            "/api/v1/jobs",
            json={
                "input_type": "text",
                "text": "法兰盘",
                "pipeline_config": {
                    "check_printability": {"enabled": False},
                },
            },
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)
        assert job_id

    def test_disabled_node_validate_warning(self, client: TestClient) -> None:
        """Disabling a core node should produce a validate warning."""
        # First get nodes to find a core node
        resp = client.get("/api/v1/pipeline/nodes")
        assert resp.status_code == 200

        # Validate with a disabled node
        resp = client.post(
            "/api/v1/pipeline/validate",
            json={
                "input_type": "text",
                "config": {},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["node_count"] > 0

    def test_strategy_availability_endpoint(self, client: TestClient) -> None:
        """Strategy availability endpoint returns data for nodes with strategies."""
        resp = client.get("/api/v1/pipeline/strategy-availability")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_confirm_with_config_updates(self, client: TestClient) -> None:
        """HITL confirm with pipeline_config_updates should be accepted."""
        # Create job via graph
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "法兰盘，外径100mm"},
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)

        # Confirm with pipeline_config_updates
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={
                "confirmed_params": {"diameter": 100.0},
                "pipeline_config_updates": {
                    "check_printability": {"enabled": False},
                },
            },
        )
        assert resp.status_code == 200

    def test_deprecated_api_headers(self, client: TestClient) -> None:
        """Deprecated APIs should return Deprecation headers."""
        resp = client.get("/api/v1/pipeline/tooltips")
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"

        resp = client.get("/api/v1/pipeline/presets")
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"

    def test_nodes_endpoint_has_config_schema(self, client: TestClient) -> None:
        """GET /pipeline/nodes should include config_schema with enhanced metadata."""
        resp = client.get("/api/v1/pipeline/nodes")
        assert resp.status_code == 200
        data = resp.json()
        nodes = data["nodes"]
        # At least some nodes should have config_schema
        schemas = [n for n in nodes if n.get("config_schema")]
        # Check that schema has properties (if any nodes have config_model)
        for node in schemas:
            schema = node["config_schema"]
            assert "properties" in schema or "type" in schema
```

**Step 2: Run E2E tests**

Run: `uv run pytest tests/e2e/test_pipeline_config_e2e.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add tests/e2e/test_pipeline_config_e2e.py
git commit -m "test: add E2E tests for pipeline config fullstack feature"
```

---

## Final Verification

After all tasks complete:

```bash
# Backend tests
uv run pytest tests/ -v

# Frontend type check
cd frontend && npx tsc --noEmit && npm run lint

# Full E2E
uv run pytest tests/e2e/ -v
```
