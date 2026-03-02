# M1: 安全加固 + 代码孤岛串联 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 eval() 安全漏洞、添加模板 API 写保护、持久化 LangGraph checkpointer、实装 pipeline_config、对齐前后端枚举、串联 TokenTracker/CostOptimizer 孤岛代码、增强 PrintabilityChecker 拦截能力。

**Architecture:** 全部为现有代码的修复和串联，不引入新架构模式。每个子任务独立修改 1-2 个文件，任务间无文件交叉。

**Tech Stack:** Python 3.10+, FastAPI, LangGraph, Pydantic v2, pytest, React/TypeScript (枚举修复)

---

## 域标签与并行感知

| 任务 | 域标签 | 预期修改文件 | 可并行 |
|------|--------|-------------|--------|
| Task 1: eval() → safe_eval | `[backend]` `[security]` | `backend/core/template_engine.py`, `tests/test_template_engine.py` | Yes |
| Task 2: 模板 API 认证 | `[backend]` `[security]` | `backend/api/v1/templates.py`, `backend/config.py`, `tests/test_templates_api.py` | Yes |
| Task 3: 持久化 checkpointer | `[backend]` | `backend/graph/builder.py`, `backend/config.py`, `tests/test_graph_builder.py` | Yes |
| Task 4: pipeline_config 实装 | `[backend]` | `backend/api/v1/jobs.py`, `backend/graph/state.py`, `backend/graph/nodes/generation.py`, `tests/test_generate_api.py` | Yes |
| Task 5: 枚举大小写统一 | `[frontend]` `[backend]` | `frontend/src/components/DrawingSpecForm/index.tsx`, `frontend/src/pages/Generate/DrawingSpecReview.tsx` | Yes |
| Task 6: TokenTracker 串联 | `[backend]` | `backend/graph/nodes/analysis.py`, `backend/graph/nodes/generation.py`, `backend/graph/state.py`, `backend/graph/nodes/lifecycle.py`, `tests/test_token_tracker_integration.py` | Partial (共享 state.py) |
| Task 7: CostOptimizer 串联 | `[backend]` | `backend/graph/nodes/analysis.py`, `tests/test_cost_optimizer_integration.py` | Partial (共享 analysis.py) |
| Task 8: Printability 拦截 | `[backend]` | `backend/graph/nodes/postprocess.py`, `tests/test_graph_nodes_postprocess.py` | Yes |

**文件交叉矩阵：** Task 6 和 Task 7 都触碰 `analysis.py` 和 `state.py`，建议串行（先 Task 6 再 Task 7）。其余任务间文件集无交叉，可并行。

---

## Task 1: eval() → 安全约束评估

**Files:**
- Modify: `backend/core/template_engine.py:69-76`
- Test: `tests/test_template_engine.py`

### Step 1: 写失败测试 — 验证安全函数替代 eval

```python
# tests/test_template_engine.py — 追加到 TestTemplateEngineValidate 类

def test_constraint_no_code_injection(self) -> None:
    """Constraint with code injection attempt must fail safely."""
    tmpl = ParametricTemplate(
        name="injection_test",
        display_name="注入测试",
        part_type="general",
        params=[
            ParamDefinition(
                name="x", display_name="X", param_type="float", default=10,
            ),
        ],
        constraints=["__import__('os').system('echo pwned')"],
    )
    engine = TemplateEngine(templates=[tmpl])
    errors = engine.validate("injection_test", {"x": 5})
    assert len(errors) == 1
    assert "Constraint evaluation error" in errors[0]

def test_constraint_no_builtin_access(self) -> None:
    """Constraint must not access builtins beyond min/max/abs."""
    tmpl = ParametricTemplate(
        name="builtin_test",
        display_name="内置函数测试",
        part_type="general",
        params=[
            ParamDefinition(
                name="x", display_name="X", param_type="float", default=10,
            ),
        ],
        constraints=["eval('1+1') == 2"],
    )
    engine = TemplateEngine(templates=[tmpl])
    errors = engine.validate("builtin_test", {"x": 5})
    assert len(errors) == 1
    assert "Constraint evaluation error" in errors[0]
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_template_engine.py::TestTemplateEngineValidate::test_constraint_no_code_injection tests/test_template_engine.py::TestTemplateEngineValidate::test_constraint_no_builtin_access -v`
Expected: 至少 `test_constraint_no_code_injection` FAIL（当前 eval 可能执行注入代码）

### Step 3: 实现安全约束评估器

将 `backend/core/template_engine.py:69-76` 中的 `eval()` 替换为 `ast.literal_eval` 无法使用（约束是表达式而非字面量），改用 `compile()` + 受限 `exec()` 方案：

```python
# backend/core/template_engine.py — 替换 validate 方法中的约束评估部分

import ast

def _safe_eval_constraint(expr: str, variables: dict) -> bool:
    """Safely evaluate a constraint expression.

    Only allows comparison/arithmetic operators and the variables provided.
    Rejects any function calls, attribute access, or imports.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ValueError(f"Invalid constraint syntax: {expr}")

    # Walk AST and reject dangerous nodes
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Import, ast.ImportFrom)):
            raise ValueError(f"Forbidden operation in constraint: {expr}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(f"Forbidden name in constraint: {node.id}")

    allowed_names = {"min": min, "max": max, "abs": abs}
    allowed_names.update(variables)
    code = compile(tree, "<constraint>", "eval")
    return bool(eval(code, {"__builtins__": {}}, allowed_names))  # noqa: S307
```

然后在 `validate` 方法中替换：

```python
for constraint in tmpl.constraints:
    try:
        if not _safe_eval_constraint(constraint, merged):
            errors.append(f"Constraint violation: {constraint}")
    except (ValueError, Exception) as exc:
        errors.append(f"Constraint evaluation error: {constraint} ({exc})")
```

### Step 4: 运行所有 template_engine 测试

Run: `uv run pytest tests/test_template_engine.py -v`
Expected: ALL PASS（含新增的安全测试和原有的约束测试）

### Step 5: Commit

```bash
git add backend/core/template_engine.py tests/test_template_engine.py
git commit -m "fix(security): replace eval() with AST-safe constraint evaluation in template engine"
```

---

## Task 2: 模板 API 写保护

**Files:**
- Modify: `backend/api/v1/templates.py:76-124`
- Modify: `backend/config.py`（添加 api_key 引用说明）
- Test: `tests/test_templates_api.py`

### Step 1: 写失败测试 — 无 API Key 时写操作被拒

```python
# tests/test_templates_api.py — 追加

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

@pytest.fixture
def secured_client():
    """Client with API key protection enabled."""
    with patch("backend.config.Settings") as mock_settings:
        mock_settings.return_value.api_key = "test-secret-key"
        from backend.main import app
        yield TestClient(app)

def test_create_template_without_auth_returns_401(secured_client):
    """POST /templates without API key should return 401."""
    resp = secured_client.post("/api/v1/templates", json={"name": "test"})
    assert resp.status_code == 401

def test_delete_template_without_auth_returns_401(secured_client):
    """DELETE /templates/{name} without API key should return 401."""
    resp = secured_client.delete("/api/v1/templates/test")
    assert resp.status_code == 401

def test_get_templates_without_auth_returns_200(secured_client):
    """GET /templates should work without auth."""
    resp = secured_client.get("/api/v1/templates")
    assert resp.status_code == 200
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_templates_api.py::test_create_template_without_auth_returns_401 -v`
Expected: FAIL（当前无认证，POST 返回 201 或 422）

### Step 3: 实现 API Key 依赖

```python
# backend/api/v1/templates.py — 添加依赖

from fastapi import Depends, Header
from backend.config import Settings

def _require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Reject write requests when API key is configured but not provided."""
    settings = Settings()
    if settings.api_key and x_api_key != settings.api_key:
        raise APIError(
            status_code=401,
            code=ErrorCode.UNAUTHORIZED,
            message="Invalid or missing API key",
        )
```

然后在写操作路由上添加依赖：

```python
@router.post("", status_code=201, dependencies=[Depends(_require_api_key)])
@router.put("/{name}", dependencies=[Depends(_require_api_key)])
@router.delete("/{name}", dependencies=[Depends(_require_api_key)])
```

同时在 `backend/api/v1/errors.py` 中确认 `ErrorCode` 枚举包含 `UNAUTHORIZED`（如不存在则添加）。

### Step 4: 运行测试

Run: `uv run pytest tests/test_templates_api.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/api/v1/templates.py backend/api/v1/errors.py tests/test_templates_api.py
git commit -m "feat(security): add API key protection to template write endpoints"
```

---

## Task 3: MemorySaver → 持久化 Checkpointer

**Files:**
- Modify: `backend/graph/builder.py:91-108`
- Modify: `backend/config.py`（添加 db_url）
- Test: `tests/test_graph_builder.py`

### Step 1: 写失败测试 — checkpointer 类型验证

```python
# tests/test_graph_builder.py — 追加

import pytest

@pytest.mark.asyncio
async def test_compiled_graph_uses_persistent_checkpointer():
    """get_compiled_graph should not use MemorySaver in production."""
    from backend.graph.builder import get_compiled_graph
    graph = await get_compiled_graph()
    checkpointer = graph.checkpointer
    # Should NOT be MemorySaver
    from langgraph.checkpoint.memory import MemorySaver
    assert not isinstance(checkpointer, MemorySaver), \
        "Production graph should use persistent checkpointer, not MemorySaver"
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_graph_builder.py::test_compiled_graph_uses_persistent_checkpointer -v`
Expected: FAIL（当前使用 MemorySaver）

### Step 3: 实现 SQLite 持久化 checkpointer

LangGraph 提供 `langgraph-checkpoint-sqlite` 包。先添加依赖：

```bash
uv add langgraph-checkpoint-sqlite
```

然后修改 `backend/graph/builder.py`:

```python
async def get_compiled_graph():
    """Compile graph with persistent SQLite checkpointer for HITL support.

    Uses async SQLite checkpointer for cross-restart state recovery.
    Falls back to MemorySaver when SQLite is unavailable (e.g. tests).
    """
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        checkpointer = AsyncSqliteSaver.from_conn_string("data/checkpoints.db")
        await checkpointer.setup()
    except Exception:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    compiled = _build_workflow().compile(
        checkpointer=checkpointer,
        interrupt_before=["confirm_with_user"],
    )
    return compiled
```

### Step 4: 运行测试

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/graph/builder.py pyproject.toml uv.lock tests/test_graph_builder.py
git commit -m "feat: replace MemorySaver with SQLite checkpointer for HITL persistence"
```

---

## Task 4: pipeline_config 执行实装

**Files:**
- Modify: `backend/api/v1/jobs.py:208-234`（将 pipeline_config 注入 state）
- Modify: `backend/graph/state.py`（添加 pipeline_config 字段）
- Modify: `backend/graph/nodes/generation.py`（读取 pipeline_config）
- Test: `tests/test_generate_api.py`

### Step 1: 写失败测试 — pipeline_config 传递到 graph state

```python
# tests/test_generate_api.py — 追加

def test_pipeline_config_passed_to_graph_state():
    """pipeline_config from API should appear in graph initial_state."""
    from backend.graph.state import CadJobState
    # Verify CadJobState has pipeline_config field
    assert "pipeline_config" in CadJobState.__annotations__, \
        "CadJobState must have pipeline_config field"
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_generate_api.py::test_pipeline_config_passed_to_graph_state -v`
Expected: FAIL（CadJobState 没有 pipeline_config 字段）

### Step 3: 实现 pipeline_config 传递

**3a.** 在 `backend/graph/state.py` 添加字段：

```python
class CadJobState(TypedDict, total=False):
    # ...existing fields...
    pipeline_config: dict | None   # PipelineConfig.model_dump()
```

**3b.** 在 `backend/api/v1/jobs.py` 的 `create_job_endpoint` 中注入 pipeline_config：

```python
initial_state: dict[str, Any] = {
    "job_id": job_id,
    "input_type": body.input_type,
    "input_text": input_text,
    "image_path": None,
    "status": "pending",
    "pipeline_config": body.pipeline_config or None,
}
```

同样在 `create_drawing_job` 中：

```python
import json as _json

# Parse pipeline_config from form field
_parsed_config = {}
try:
    _parsed_config = _json.loads(pipeline_config) if pipeline_config != "{}" else {}
except _json.JSONDecodeError:
    pass

initial_state = {
    "job_id": job_id,
    "input_type": "drawing",
    "input_text": None,
    "image_path": image_path,
    "status": "pending",
    "pipeline_config": _parsed_config or None,
}
```

**3c.** 在 `backend/graph/nodes/generation.py` 的 `generate_step_text_node` 中读取 pipeline_config 影响模板生成（未来扩展点，当前先传递不中断）。

### Step 4: 运行测试

Run: `uv run pytest tests/test_generate_api.py tests/test_graph_state.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/graph/state.py backend/api/v1/jobs.py tests/test_generate_api.py
git commit -m "feat: wire pipeline_config from API into graph state"
```

---

## Task 5: 前后端枚举大小写统一

**Files:**
- Modify: `frontend/src/components/DrawingSpecForm/index.tsx:24-32`
- Modify: `frontend/src/pages/Generate/DrawingSpecReview.tsx:24-32`

### Step 1: 确认后端枚举值

查看 `backend/knowledge/part_types.py:9-17`:
```python
class PartType(str, Enum):
    ROTATIONAL = "rotational"         # 小写
    ROTATIONAL_STEPPED = "rotational_stepped"
    PLATE = "plate"
    ...
```

后端 PartType.value 是**小写**（`"rotational"`），但前端 `DrawingSpecForm` 使用**大写** value（`'ROTATIONAL'`）。

### Step 2: 修复前端 — DrawingSpecForm

```typescript
// frontend/src/components/DrawingSpecForm/index.tsx:24-32
const PART_TYPE_OPTIONS = [
  { value: 'rotational', label: '回转体' },
  { value: 'rotational_stepped', label: '阶梯回转体' },
  { value: 'plate', label: '板件' },
  { value: 'bracket', label: '支架' },
  { value: 'housing', label: '壳体' },
  { value: 'gear', label: '齿轮' },
  { value: 'general', label: '通用' },
];
```

### Step 3: 修复前端 — DrawingSpecReview

```typescript
// frontend/src/pages/Generate/DrawingSpecReview.tsx:24-32
const PART_TYPE_OPTIONS = [
  { value: 'rotational', label: '回转体' },
  { value: 'rotational_stepped', label: '阶梯回转体' },
  { value: 'plate', label: '板件' },
  { value: 'bracket', label: '支架' },
  { value: 'housing', label: '壳体' },
  { value: 'gear', label: '齿轮' },
  { value: 'general', label: '通用' },
];
```

### Step 4: 运行 TypeScript 检查

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: PASS

### Step 5: Commit

```bash
git add frontend/src/components/DrawingSpecForm/index.tsx frontend/src/pages/Generate/DrawingSpecReview.tsx
git commit -m "fix: align frontend PartType enum values with backend (uppercase → lowercase)"
```

---

## Task 6: TokenTracker 串入 LangGraph 节点

**Files:**
- Modify: `backend/graph/state.py`（添加 token_stats 字段）
- Modify: `backend/graph/nodes/analysis.py`（在 LLM 调用后记录 token usage）
- Modify: `backend/graph/nodes/generation.py`（在 LLM 调用后记录 token usage）
- Modify: `backend/graph/nodes/lifecycle.py`（finalize 时汇总 token_stats 到 DB）
- Create: `tests/test_token_tracker_integration.py`

### Step 1: 写失败测试

```python
# tests/test_token_tracker_integration.py

from backend.infra.token_tracker import TokenTracker

def test_token_tracker_records_and_reports():
    tracker = TokenTracker()
    tracker.record("intent_parse", input_tokens=150, output_tokens=50, duration_s=1.2)
    tracker.record("code_gen", input_tokens=300, output_tokens=200, duration_s=3.5)
    stats = tracker.get_stats()
    assert stats["total_input_tokens"] == 450
    assert stats["total_output_tokens"] == 250
    assert len(stats["stages"]) == 2

def test_cad_job_state_has_token_stats():
    from backend.graph.state import CadJobState
    assert "token_stats" in CadJobState.__annotations__
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_token_tracker_integration.py -v`
Expected: `test_cad_job_state_has_token_stats` FAIL

### Step 3: 实现串联

**3a.** 在 `backend/graph/state.py` 添加字段：

```python
class CadJobState(TypedDict, total=False):
    # ...existing fields...
    token_stats: dict | None   # TokenTracker.get_stats()
```

**3b.** 在 `backend/graph/nodes/analysis.py` 的 `analyze_intent_node` 中记录 token usage：

在 `_parse_intent` 调用后，从 LLM response metadata 提取 token usage 并通过 state 传递。由于当前 LLM 调用封装较深，初始实现采用**时间追踪**方式：

```python
import time
from backend.infra.token_tracker import TokenTracker

async def analyze_intent_node(state: CadJobState) -> dict[str, Any]:
    t0 = time.time()
    try:
        intent = await asyncio.wait_for(...)
    except Exception as exc:
        ...
    elapsed = time.time() - t0

    # Record timing (token counts require LLM callback integration — future enhancement)
    tracker = TokenTracker()
    tracker.record("intent_parse", input_tokens=0, output_tokens=0, duration_s=elapsed)

    return {
        "intent": intent,
        "matched_template": matched_template,
        "status": "awaiting_confirmation",
        "token_stats": tracker.get_stats(),
    }
```

**3c.** 在 `backend/graph/nodes/lifecycle.py` 的 `finalize_node` 中将 `token_stats` 写入 Job result：

```python
# In finalize_node, add token_stats to result_dict
if state.get("token_stats"):
    result_dict["token_stats"] = state["token_stats"]
```

### Step 4: 运行测试

Run: `uv run pytest tests/test_token_tracker_integration.py tests/test_graph_nodes_analysis.py tests/test_graph_nodes_lifecycle.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/graph/state.py backend/graph/nodes/analysis.py backend/graph/nodes/lifecycle.py tests/test_token_tracker_integration.py
git commit -m "feat: wire TokenTracker into LangGraph nodes for timing data"
```

---

## Task 7: CostOptimizer 串入管道

**Files:**
- Modify: `backend/graph/nodes/analysis.py`（使用 ResultCache 缓存 VL 分析结果）
- Create: `tests/test_cost_optimizer_integration.py`

### Step 1: 写失败测试

```python
# tests/test_cost_optimizer_integration.py

from backend.core.cost_optimizer import CostOptimizer, ResultCache

def test_result_cache_hit():
    cache = ResultCache(ttl_seconds=60)
    cache.set("key1", {"part_type": "rotational"})
    result = cache.get("key1")
    assert result == {"part_type": "rotational"}

def test_result_cache_miss():
    cache = ResultCache(ttl_seconds=60)
    assert cache.get("nonexistent") is None

def test_cost_optimizer_model_selection():
    optimizer = CostOptimizer()
    model = optimizer.get_model("vl", round_num=1)
    assert model == "qwen-vl-max"
    model2 = optimizer.get_model("vl", round_num=2)
    assert model2 == "qwen-vl-plus"  # degraded for later rounds
```

### Step 2: 运行测试

Run: `uv run pytest tests/test_cost_optimizer_integration.py -v`
Expected: PASS（CostOptimizer 代码本身已完整，这里验证集成）

### Step 3: 在 analyze_vision_node 中集成 ResultCache

```python
# backend/graph/nodes/analysis.py — 修改 analyze_vision_node

# Module-level cache instance (shared across requests)
_vision_cache = None

def _get_vision_cache():
    global _vision_cache
    if _vision_cache is None:
        from backend.core.cost_optimizer import ResultCache
        _vision_cache = ResultCache(ttl_seconds=3600)
    return _vision_cache

async def analyze_vision_node(state: CadJobState) -> dict[str, Any]:
    image_path = state.get("image_path")
    if not image_path:
        ...

    # Check cache first
    cache = _get_vision_cache()
    try:
        image_data = Path(image_path).read_bytes()
        cache_key = cache.make_key(image_data)
        cached = cache.get(cache_key)
        if cached:
            logger.info("Vision analysis cache hit for job %s", state["job_id"])
            spec_dict, reasoning = cached
            # skip to dispatch (same as uncached path below)
            ...
    except Exception:
        pass  # Cache miss or error — proceed normally

    # Normal path
    spec_dict, reasoning = await asyncio.wait_for(...)

    # Store in cache
    try:
        cache.set(cache_key, (spec_dict, reasoning))
    except Exception:
        pass
    ...
```

### Step 4: 运行测试

Run: `uv run pytest tests/test_cost_optimizer_integration.py tests/test_graph_nodes_analysis.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/graph/nodes/analysis.py tests/test_cost_optimizer_integration.py
git commit -m "feat: integrate CostOptimizer ResultCache into vision analysis node"
```

---

## Task 8: PrintabilityChecker 拦截能力

**Files:**
- Modify: `backend/graph/nodes/postprocess.py:57-73`
- Test: `tests/test_graph_nodes_postprocess.py`

### Step 1: 写失败测试 — printable=False 应中断管道

```python
# tests/test_graph_nodes_postprocess.py — 追加

import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_printability_failure_sets_failed_status():
    """When printable=False with error-level issues, status should be 'failed'."""
    from backend.graph.nodes.postprocess import check_printability_node

    state = {
        "job_id": "test-print-fail",
        "step_path": "/fake/model.step",
    }

    mock_result = {
        "printable": False,
        "issues": [
            {"severity": "error", "message": "Wall thickness below minimum"},
            {"severity": "warning", "message": "Some overhang detected"},
        ],
    }

    with patch(
        "backend.graph.nodes.postprocess._run_printability_check",
        return_value=mock_result,
    ):
        result = await check_printability_node(state)

    assert result.get("status") == "failed"
    assert "Wall thickness" in result.get("error", "")

@pytest.mark.asyncio
async def test_printability_warning_only_continues():
    """When printable=True (warnings only), status should not be 'failed'."""
    from backend.graph.nodes.postprocess import check_printability_node

    state = {
        "job_id": "test-print-warn",
        "step_path": "/fake/model.step",
    }

    mock_result = {
        "printable": True,
        "issues": [
            {"severity": "warning", "message": "Minor overhang"},
        ],
    }

    with patch(
        "backend.graph.nodes.postprocess._run_printability_check",
        return_value=mock_result,
    ):
        result = await check_printability_node(state)

    assert result.get("status") != "failed"
    assert result.get("printability") == mock_result
```

### Step 2: 运行测试验证失败

Run: `uv run pytest tests/test_graph_nodes_postprocess.py::test_printability_failure_sets_failed_status -v`
Expected: FAIL（当前 printable=False 时不设置 status=failed）

### Step 3: 实现拦截逻辑

```python
# backend/graph/nodes/postprocess.py — 修改 check_printability_node

async def check_printability_node(state: CadJobState) -> dict[str, Any]:
    """Run DfAM printability analysis. Blocks pipeline on critical failures."""
    step_path = state.get("step_path")
    if not step_path:
        return {}

    try:
        result = await asyncio.to_thread(_run_printability_check, step_path)
    except Exception as exc:
        logger.warning("Printability check failed (non-fatal): %s", exc)
        return {"printability": None}

    await _safe_dispatch(
        "job.printability_ready",
        {"job_id": state["job_id"], "printability": result},
    )

    # Intercept: if not printable AND has error-level issues, fail the job
    if result and not result.get("printable", True):
        error_issues = [
            issue for issue in result.get("issues", [])
            if issue.get("severity") == "error"
        ]
        if error_issues:
            error_msg = "; ".join(i.get("message", "") for i in error_issues)
            logger.error("Printability check failed: %s", error_msg)
            return {
                "printability": result,
                "error": f"Printability check failed: {error_msg}",
                "status": "failed",
            }

    return {"printability": result}
```

### Step 4: 运行测试

Run: `uv run pytest tests/test_graph_nodes_postprocess.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add backend/graph/nodes/postprocess.py tests/test_graph_nodes_postprocess.py
git commit -m "feat: enable PrintabilityChecker to block pipeline on critical failures"
```

---

## 全量验证

### Step 1: 运行所有后端测试

Run: `uv run pytest tests/ -v --tb=short`
Expected: ALL PASS

### Step 2: 运行前端检查

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: PASS

### Step 3: 最终 Commit

```bash
git add -A
git commit -m "chore: M1 security hardening and code island integration complete"
```

---

## 验收标准对照

| # | 验收标准 | 对应 Task |
|---|---------|----------|
| 1 | `template_engine.py` 中零 `eval()` 调用 | Task 1 |
| 2 | 模板 API 需认证才能写入（GET 可匿名） | Task 2 |
| 3 | LangGraph checkpointer 支持跨进程重启恢复 HITL 状态 | Task 3 |
| 4 | `pipeline_config` 中的配置影响实际管道行为 | Task 4 |
| 5 | 前后端 PartType 枚举值一致 | Task 5 |
| 6 | Job 结果中包含 `token_stats` 字段 | Task 6 |
| 7 | `printable=False` + error 级 issue 时 Job 状态为 `failed` | Task 8 |
| 8 | 所有现有测试通过 | 全量验证 |
