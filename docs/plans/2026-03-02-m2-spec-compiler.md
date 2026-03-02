# M2: SpecCompiler + 精密路径架构重构 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `team-driven-development` to execute this plan with Agent Team.

**Goal:** 引入 SpecCompiler 统一调度器，消除精密路径代码散布，补齐 LLM fallback + 语义路由 + 后加工推荐 + 拦截器注册表。

**Architecture:** SpecCompiler 封装「模板优先 → LLM fallback」双策略，由 `generate_step_text_node` 调用。模板路由从关键字匹配升级为 `part_type + 参数覆盖率` 评分。后加工推荐引擎基于 printability 结果生成建议。拦截器注册表在 `_build_workflow()` 构建时插入节点。

**Tech Stack:** Python 3.10+, LangGraph, Pydantic v2, Jinja2, CadQuery (via SafeExecutor)

**OpenSpec Change:** `openspec/changes/spec-compiler-precision-pipeline/`

---

## Agent Team 执行结构

```
Phase 0（串行，team lead）: 共享接口 + SpecCompiler 核心 — Task 0-4
Phase 1（并行，4 agents）:
    Agent A: generation 节点重构 — Task 5-6
    Agent B: 模板语义路由 — Task 7-9
    Agent C: 后加工推荐引擎 — Task 10-13
    Agent D: 拦截器注册表 — Task 14-16
Phase 2（串行，team lead）: 集成验证 + 清理 — Task 17
```

## 文件交叉矩阵

| 并行组 | 修改文件 |
|--------|---------|
| **Agent A** | `backend/graph/nodes/generation.py`, `tests/test_graph_nodes_generation.py` |
| **Agent B** | `backend/graph/nodes/analysis.py`, `tests/test_template_routing.py` |
| **Agent C** | `backend/core/recommendation_engine.py`(新), `backend/graph/nodes/postprocess.py`, `backend/graph/nodes/lifecycle.py`, `tests/test_recommendation_engine.py` |
| **Agent D** | `backend/graph/interceptors.py`(新), `backend/graph/builder.py`, `tests/test_interceptor_registry.py` |

**交叉检查：4 组文件集无交叉 ✅**

Phase 0 预先完成的共享文件（不在并行范围内）：
- `backend/core/spec_compiler.py` (新建)
- `backend/graph/state.py` (添加 `recommendations` 字段)
- `tests/test_spec_compiler.py` (新建)

---

## Phase 0: 共享接口 + SpecCompiler 核心（串行，team lead）

### Task 0: 添加 recommendations 字段到 state.py

**Files:**
- Modify: `backend/graph/state.py:28-29`

**Step 1: 添加字段**

在 `printability: dict | None` 之后添加：

```python
    recommendations: list[dict] | None  # ParamRecommendation / PostProcessRecommendation
```

**Step 2: 验证现有测试不受影响**

Run: `uv run pytest tests/test_graph_builder.py -v`
Expected: PASS (TypedDict total=False，新字段可选)

**Step 3: Commit**

```bash
git add backend/graph/state.py
git commit -m "feat(m2): add recommendations field to CadJobState"
```

---

### Task 1: 创建 SpecCompiler 骨架 + CompileResult

**Files:**
- Create: `backend/core/spec_compiler.py`
- Test: `tests/test_spec_compiler.py`

**Step 1: 写测试骨架**

```python
"""Tests for SpecCompiler — unified code compilation dispatch."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from backend.core.spec_compiler import SpecCompiler, CompileResult, CompilationError


class TestCompileResult:
    def test_template_result(self):
        r = CompileResult(method="template", template_name="cylinder_simple", step_path="/tmp/model.step")
        assert r.method == "template"
        assert r.template_name == "cylinder_simple"

    def test_llm_result(self):
        r = CompileResult(method="llm_fallback", step_path="/tmp/model.step")
        assert r.method == "llm_fallback"
        assert r.template_name is None


class TestSpecCompilerInit:
    def test_creates_instance(self):
        compiler = SpecCompiler()
        assert compiler is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_spec_compiler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.core.spec_compiler'`

**Step 3: 创建 spec_compiler.py 骨架**

```python
"""SpecCompiler — unified code compilation dispatch.

Encapsulates the template-first-then-LLM-fallback strategy:
1. Try TemplateEngine.render() + SafeExecutor if matched_template is set
2. Fall back to V2 pipeline CodeGeneratorChain if template path fails or is unavailable
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CompilationError(Exception):
    """Raised when both template and LLM paths fail."""


@dataclass
class CompileResult:
    """Result of a SpecCompiler.compile() call."""

    method: str  # "template" | "llm_fallback"
    step_path: str = ""
    template_name: str | None = None
    cadquery_code: str = ""
    errors: list[str] = field(default_factory=list)


class SpecCompiler:
    """Stateless dispatcher: template-first, LLM-fallback.

    Usage::

        compiler = SpecCompiler()
        result = compiler.compile(
            matched_template="cylinder_simple",
            params={"diameter": 50, "height": 100},
            output_path="/tmp/model.step",
        )
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._templates_dir = templates_dir or (
            Path(__file__).parent.parent / "knowledge" / "templates"
        )

    def compile(
        self,
        *,
        matched_template: str | None,
        params: dict[str, Any],
        output_path: str,
        input_text: str = "",
        intent: dict | None = None,
    ) -> CompileResult:
        """Compile params into a STEP file.

        Strategy:
        1. If matched_template is set → render + execute
        2. Else → LLM fallback via V2 pipeline
        """
        if matched_template:
            try:
                return self._compile_from_template(matched_template, params, output_path)
            except Exception as exc:
                logger.warning("Template compilation failed (%s), trying LLM fallback", exc)

        # LLM fallback
        try:
            return self._compile_from_llm(params, output_path, input_text, intent)
        except Exception as llm_exc:
            raise CompilationError(
                f"Both template and LLM paths failed. "
                f"Template: {matched_template!r}, LLM error: {llm_exc}"
            ) from llm_exc

    def _compile_from_template(
        self, template_name: str, params: dict, output_path: str
    ) -> CompileResult:
        """Render template + execute in sandbox."""
        from backend.core.template_engine import TemplateEngine
        from backend.infra.sandbox import SafeExecutor

        engine = TemplateEngine.from_directory(self._templates_dir)
        code = engine.render(template_name, params, output_filename=output_path)

        executor = SafeExecutor(timeout_s=120)
        result = executor.execute(code)
        if not result.success:
            raise RuntimeError(f"Sandbox execution failed: {result.stderr}")
        if not Path(output_path).exists():
            raise RuntimeError(f"STEP file not created at {output_path}")

        return CompileResult(
            method="template",
            template_name=template_name,
            step_path=output_path,
            cadquery_code=code,
        )

    def _compile_from_llm(
        self, params: dict, output_path: str, input_text: str, intent: dict | None
    ) -> CompileResult:
        """Fall back to V2 pipeline CodeGeneratorChain."""
        from backend.pipeline.pipeline import generate_step_from_2d_cad_image

        # Build description from intent or params
        description = input_text
        if not description and intent:
            description = intent.get("raw_text", str(params))

        # Use V2 pipeline (stages 1.5-5) for LLM-based generation
        generate_step_from_2d_cad_image(
            image_filepath="",  # no image for text path
            output_filepath=output_path,
        )

        if not Path(output_path).exists():
            raise RuntimeError(f"LLM generation failed: STEP file not created at {output_path}")

        return CompileResult(
            method="llm_fallback",
            step_path=output_path,
        )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_spec_compiler.py::TestCompileResult -v`
Expected: PASS

Run: `uv run pytest tests/test_spec_compiler.py::TestSpecCompilerInit -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/core/spec_compiler.py tests/test_spec_compiler.py
git commit -m "feat(m2): add SpecCompiler skeleton + CompileResult dataclass"
```

---

### Task 2: 实现 SpecCompiler 模板路径测试

**Files:**
- Modify: `tests/test_spec_compiler.py`

**Step 1: 写模板路径测试**

```python
class TestCompileFromTemplate:
    @patch("backend.core.spec_compiler.SafeExecutor")
    @patch("backend.core.spec_compiler.TemplateEngine")
    def test_template_success(self, MockEngine, MockExecutor):
        # Setup mocks
        engine = MockEngine.from_directory.return_value
        engine.render.return_value = "import cadquery as cq; cq.Workplane('XY').box(10,10,10)"
        executor_inst = MockExecutor.return_value
        executor_inst.execute.return_value = MagicMock(success=True, stderr="")

        compiler = SpecCompiler()
        with patch("backend.core.spec_compiler.Path") as MockPath:
            MockPath.return_value.exists.return_value = True
            result = compiler.compile(
                matched_template="cylinder_simple",
                params={"diameter": 50},
                output_path="/tmp/model.step",
            )

        assert result.method == "template"
        assert result.template_name == "cylinder_simple"
        engine.render.assert_called_once()

    @patch("backend.core.spec_compiler.SafeExecutor")
    @patch("backend.core.spec_compiler.TemplateEngine")
    def test_template_fail_falls_back_to_llm(self, MockEngine, MockExecutor):
        engine = MockEngine.from_directory.return_value
        engine.render.side_effect = RuntimeError("Template render error")

        compiler = SpecCompiler()
        # LLM fallback will also fail in test (no real pipeline)
        with pytest.raises(CompilationError, match="Both template and LLM"):
            compiler.compile(
                matched_template="bad_template",
                params={},
                output_path="/tmp/model.step",
            )

    def test_no_template_goes_to_llm(self):
        compiler = SpecCompiler()
        # Without mocking LLM, this should raise CompilationError
        with pytest.raises((CompilationError, Exception)):
            compiler.compile(
                matched_template=None,
                params={},
                output_path="/tmp/model.step",
            )
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_spec_compiler.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_spec_compiler.py
git commit -m "test(m2): add SpecCompiler template + fallback tests"
```

---

### Task 3: 实现模板路由评分函数

**Files:**
- Modify: `backend/core/spec_compiler.py`
- Modify: `tests/test_spec_compiler.py`

**Step 1: 写评分测试**

```python
class TestRankTemplates:
    def test_higher_coverage_wins(self):
        """Template with more matching params should rank first."""
        from backend.core.spec_compiler import rank_templates

        # Mock templates with different param sets
        t1 = MagicMock()
        t1.name = "simple"
        t1.params = [MagicMock(name="diameter"), MagicMock(name="height")]

        t2 = MagicMock()
        t2.name = "complex"
        t2.params = [MagicMock(name="diameter"), MagicMock(name="height"), MagicMock(name="wall_thickness"), MagicMock(name="fillet_radius")]

        known_params = {"diameter": 50, "height": 100}
        ranked = rank_templates([t1, t2], known_params)
        # t1 has 2/2 coverage (1.0), t2 has 2/4 coverage (0.5)
        assert ranked[0].name == "simple"

    def test_empty_candidates_returns_empty(self):
        from backend.core.spec_compiler import rank_templates
        assert rank_templates([], {"x": 1}) == []

    def test_same_score_fewer_params_wins(self):
        from backend.core.spec_compiler import rank_templates
        t1 = MagicMock()
        t1.name = "a"
        t1.params = [MagicMock(name="d"), MagicMock(name="h"), MagicMock(name="extra")]
        t2 = MagicMock()
        t2.name = "b"
        t2.params = [MagicMock(name="d"), MagicMock(name="h")]
        ranked = rank_templates([t1, t2], {"d": 1, "h": 2})
        assert ranked[0].name == "b"  # fewer params → simpler
```

**Step 2: 实现 rank_templates**

在 `spec_compiler.py` 顶层添加：

```python
def rank_templates(
    candidates: list,
    known_params: dict[str, Any],
) -> list:
    """Rank template candidates by parameter coverage.

    Coverage = len(known ∩ template_params) / len(template_params).
    Ties broken by fewer total params (simpler template preferred).
    """
    if not candidates:
        return []

    def _score(tpl) -> tuple[float, int]:
        param_names = {p.name for p in tpl.params}
        overlap = len(param_names & set(known_params.keys()))
        coverage = overlap / len(param_names) if param_names else 0.0
        return (-coverage, len(param_names))  # negative for descending sort

    return sorted(candidates, key=_score)
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_spec_compiler.py::TestRankTemplates -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/core/spec_compiler.py tests/test_spec_compiler.py
git commit -m "feat(m2): add rank_templates scoring function"
```

---

### Task 4: 运行全量测试，确认 Phase 0 稳定

**Step 1: 全量测试**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS (1236+ tests)

**Step 2: Commit 并标记 Phase 0 完成**

```bash
git commit --allow-empty -m "[impl] M2 Phase 0 complete: SpecCompiler + state.recommendations"
```

---

## Phase 1: 并行模块开发（4 agents）

---

### Agent A: generation 节点重构

**修改文件（独占）:**
- `backend/graph/nodes/generation.py`
- `tests/test_graph_nodes_generation.py`

#### Task 5: 重构 generate_step_text_node 使用 SpecCompiler

**Files:**
- Modify: `backend/graph/nodes/generation.py:19-109`
- Test: `tests/test_graph_nodes_generation.py`

**Step 1: 写测试**

```python
"""Tests for generation nodes with SpecCompiler integration."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import asyncio

from backend.core.spec_compiler import CompileResult, CompilationError


class TestGenerateStepTextNode:
    @pytest.fixture
    def base_state(self):
        return {
            "job_id": "test-job-1",
            "input_type": "text",
            "input_text": "生成一个圆柱体",
            "matched_template": "cylinder_simple",
            "confirmed_params": {"diameter": 50, "height": 100},
            "token_stats": {"stages": []},
        }

    @patch("backend.graph.nodes.generation.SpecCompiler")
    @patch("backend.graph.nodes.lifecycle._safe_dispatch", new_callable=AsyncMock)
    def test_template_path(self, mock_dispatch, MockCompiler, base_state):
        from backend.graph.nodes.generation import generate_step_text_node

        compiler = MockCompiler.return_value
        compiler.compile.return_value = CompileResult(
            method="template", template_name="cylinder_simple", step_path="/tmp/model.step"
        )
        result = asyncio.get_event_loop().run_until_complete(
            generate_step_text_node(base_state)
        )
        assert result["step_path"] == "/tmp/model.step"
        # Check SSE dispatched with stage="template"
        calls = [c for c in mock_dispatch.call_args_list if c[0][0] == "job.generating"]
        assert any("template" in str(c) for c in calls)

    @patch("backend.graph.nodes.generation.SpecCompiler")
    @patch("backend.graph.nodes.lifecycle._safe_dispatch", new_callable=AsyncMock)
    def test_llm_fallback_path(self, mock_dispatch, MockCompiler, base_state):
        from backend.graph.nodes.generation import generate_step_text_node

        base_state["matched_template"] = None
        compiler = MockCompiler.return_value
        compiler.compile.return_value = CompileResult(
            method="llm_fallback", step_path="/tmp/model.step"
        )
        result = asyncio.get_event_loop().run_until_complete(
            generate_step_text_node(base_state)
        )
        assert result["step_path"] == "/tmp/model.step"

    @patch("backend.graph.nodes.generation.SpecCompiler")
    @patch("backend.graph.nodes.lifecycle._safe_dispatch", new_callable=AsyncMock)
    def test_both_fail(self, mock_dispatch, MockCompiler, base_state):
        from backend.graph.nodes.generation import generate_step_text_node

        compiler = MockCompiler.return_value
        compiler.compile.side_effect = CompilationError("all failed")
        result = asyncio.get_event_loop().run_until_complete(
            generate_step_text_node(base_state)
        )
        assert result["status"] == "failed"
        assert "all failed" in result["error"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_graph_nodes_generation.py -v`
Expected: FAIL (SpecCompiler not yet wired in)

**Step 3: 重构 generation.py**

Replace lines 19-109 of `generation.py`:

```python
# Remove old _run_template_generation function entirely (lines 19-43).
# Replace generate_step_text_node (lines 71-109):

from backend.core.spec_compiler import SpecCompiler, CompilationError

async def generate_step_text_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from text intent via SpecCompiler (template-first, LLM-fallback)."""
    import time as _time

    _t0 = _time.time()
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    matched = state.get("matched_template")
    stage = "template" if matched else "llm_fallback"
    await _safe_dispatch(
        "job.generating",
        {"job_id": state["job_id"], "stage": stage, "status": "generating"},
    )

    try:
        compiler = SpecCompiler()
        result = await asyncio.to_thread(
            compiler.compile,
            matched_template=matched,
            params=state.get("confirmed_params") or {},
            output_path=step_path,
            input_text=state.get("input_text") or "",
            intent=state.get("intent"),
        )
        # If method changed (template failed → llm_fallback), dispatch updated stage
        if result.method != stage:
            await _safe_dispatch(
                "job.generating",
                {"job_id": state["job_id"], "stage": result.method, "status": "generating"},
            )
    except (CompilationError, Exception) as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Text generation failed: %s (%s)", exc, reason)
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    _duration = _time.time() - _t0
    token_stats = dict(state.get("token_stats") or {})
    stages = list(token_stats.get("stages", []))
    stages.append({"name": "generate_step_text", "input_tokens": 0, "output_tokens": 0, "duration_s": round(_duration, 3)})
    token_stats["stages"] = stages

    return {"step_path": result.step_path, "status": "generating", "token_stats": token_stats}
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_graph_nodes_generation.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/graph/nodes/generation.py tests/test_graph_nodes_generation.py
git commit -m "feat(m2): wire SpecCompiler into generate_step_text_node"
```

---

#### Task 6: 清理遗留代码

**Files:**
- Modify: `backend/graph/nodes/generation.py`

**Step 1: 删除 `_run_template_generation` 函数**

Remove the entire `_run_template_generation` function (was lines 19-43, should be gone after Task 5). Verify no imports reference it.

**Step 2: Run full generation tests**

Run: `uv run pytest tests/test_graph_nodes_generation.py tests/test_graph_builder.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/graph/nodes/generation.py
git commit -m "refactor(m2): remove legacy _run_template_generation wrapper"
```

---

### Agent B: 模板语义路由

**修改文件（独占）:**
- `backend/graph/nodes/analysis.py`
- `tests/test_template_routing.py`（新建）

#### Task 7: 重构 analyze_intent_node 模板匹配

**Files:**
- Modify: `backend/graph/nodes/analysis.py:86-107`
- Create: `tests/test_template_routing.py`

**Step 1: 写路由测试**

```python
"""Tests for part_type-based template routing in analyze_intent_node."""
import pytest
from unittest.mock import patch, MagicMock


class TestTemplateRouting:
    def test_part_type_routes_to_matching_templates(self):
        """find_matches should be called with part_type, not keyword search."""
        from backend.core.spec_compiler import rank_templates

        tpl = MagicMock()
        tpl.name = "cylinder_simple"
        tpl.params = [MagicMock(name="diameter"), MagicMock(name="height")]
        tpl.part_type = "rotational"

        result = rank_templates([tpl], {"diameter": 50, "height": 100})
        assert result[0].name == "cylinder_simple"

    def test_no_match_returns_none(self):
        from backend.core.spec_compiler import rank_templates
        assert rank_templates([], {"diameter": 50}) == []

    def test_ranking_prefers_higher_coverage(self):
        from backend.core.spec_compiler import rank_templates

        t1 = MagicMock()
        t1.name = "full_match"
        t1.params = [MagicMock(name="diameter"), MagicMock(name="height")]

        t2 = MagicMock()
        t2.name = "partial_match"
        t2.params = [MagicMock(name="diameter"), MagicMock(name="height"), MagicMock(name="wall")]

        ranked = rank_templates([t1, t2], {"diameter": 50, "height": 100})
        assert ranked[0].name == "full_match"
```

**Step 2: Run test to verify it passes** (rank_templates already implemented in Phase 0)

Run: `uv run pytest tests/test_template_routing.py -v`
Expected: PASS

**Step 3: 重构 analysis.py 模板匹配块**

Replace lines 86-107 of `analysis.py`:

```python
    # Template matching via part_type semantic routing (replaces keyword _match_template)
    matched_template = None
    template_params: list[dict] = []
    try:
        from backend.core.template_engine import TemplateEngine
        from backend.core.spec_compiler import rank_templates

        _templates_dir = Path(__file__).parent.parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)

        part_type = None
        if isinstance(intent, dict):
            part_type = intent.get("part_type")
        if part_type:
            candidates = engine.find_matches(part_type)
        else:
            candidates = engine.list_templates()

        known = intent.get("known_params", {}) if isinstance(intent, dict) else {}
        ranked = rank_templates(candidates, known)

        if ranked:
            tpl = ranked[0]
            matched_template = tpl.name
            template_params = []
            for p in tpl.params:
                d = p.model_dump()
                if p.name in known:
                    d["default"] = known[p.name]
                elif p.display_name and p.display_name in known:
                    d["default"] = known[p.display_name]
                template_params.append(d)
    except Exception:
        pass
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_template_routing.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/graph/nodes/analysis.py tests/test_template_routing.py
git commit -m "feat(m2): replace keyword matching with part_type semantic routing"
```

---

#### Task 8: 集成 EngineeringStandards 推荐

**Files:**
- Modify: `backend/graph/nodes/analysis.py:109-134`

**Step 1: 在模板匹配后添加推荐调用**

在 `_safe_dispatch("job.intent_analyzed", ...)` 之前插入：

```python
    # Engineering standards recommendations (best-effort)
    recommendations: list[dict] = []
    try:
        from backend.core.engineering_standards import EngineeringStandards

        part_type_for_rec = None
        if isinstance(intent, dict):
            part_type_for_rec = intent.get("part_type")
        if part_type_for_rec:
            known_for_rec = intent.get("known_params", {}) if isinstance(intent, dict) else {}
            standards = EngineeringStandards()
            recs = standards.recommend_params(part_type_for_rec, known_for_rec)
            recommendations = [r.model_dump() for r in recs]
    except Exception:
        pass
```

**Step 2: 更新 SSE 事件包含 recommendations**

在 `_safe_dispatch("job.intent_analyzed", {...})` 的 payload dict 中添加：
```python
            "recommendations": recommendations,
```

**Step 3: 更新返回值包含 recommendations**

在 return dict 中添加：
```python
        "recommendations": recommendations,
```

**Step 4: Run tests**

Run: `uv run pytest tests/ -k "intent" -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/graph/nodes/analysis.py
git commit -m "feat(m2): integrate EngineeringStandards recommendations into intent analysis"
```

---

#### Task 9: 写 EngineeringStandards 集成测试

**Files:**
- Modify: `tests/test_template_routing.py`

**Step 1: 添加推荐集成测试**

```python
class TestEngineeringStandardsIntegration:
    def test_recommend_params_rotational(self):
        from backend.core.engineering_standards import EngineeringStandards
        standards = EngineeringStandards()
        recs = standards.recommend_params("rotational", {"diameter": 50})
        # Should return flange + bolt recommendations
        assert isinstance(recs, list)
        # Each rec has param_name, value, unit, reason
        for r in recs:
            assert hasattr(r, "param_name")
            assert hasattr(r, "value")

    def test_recommend_params_unknown_type(self):
        from backend.core.engineering_standards import EngineeringStandards
        standards = EngineeringStandards()
        recs = standards.recommend_params("unknown_type", {"x": 1})
        assert recs == []
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_template_routing.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_template_routing.py
git commit -m "test(m2): add EngineeringStandards integration tests"
```

---

### Agent C: 后加工推荐引擎

**修改文件（独占）:**
- `backend/core/recommendation_engine.py`（新建）
- `backend/graph/nodes/postprocess.py`
- `backend/graph/nodes/lifecycle.py`
- `tests/test_recommendation_engine.py`（新建）

#### Task 10: 创建 recommendation_engine.py

**Files:**
- Create: `backend/core/recommendation_engine.py`
- Create: `tests/test_recommendation_engine.py`

**Step 1: 写测试**

```python
"""Tests for PostProcessRecommendationEngine."""
import pytest

from backend.core.recommendation_engine import (
    PostProcessRecommendation,
    generate_recommendations,
)


class TestGenerateRecommendations:
    def test_thin_wall_produces_thicken_action(self):
        printability = {
            "printable": True,
            "issues": [
                {"type": "thin_wall", "severity": "warning", "message": "Wall < 0.8mm at region X"}
            ],
        }
        recs = generate_recommendations(printability)
        assert len(recs) >= 1
        assert any(r.action == "thicken_wall" for r in recs)

    def test_overhang_produces_support_action(self):
        printability = {
            "printable": True,
            "issues": [
                {"type": "overhang", "severity": "warning", "message": "Overhang > 45deg"}
            ],
        }
        recs = generate_recommendations(printability)
        assert any(r.action == "add_support" for r in recs)

    def test_no_issues_produces_empty(self):
        printability = {"printable": True, "issues": []}
        recs = generate_recommendations(printability)
        assert recs == []

    def test_none_printability_returns_empty(self):
        recs = generate_recommendations(None)
        assert recs == []

    def test_recommendation_fields(self):
        printability = {
            "printable": True,
            "issues": [
                {"type": "thin_wall", "severity": "warning", "message": "test"}
            ],
        }
        recs = generate_recommendations(printability)
        r = recs[0]
        assert r.action
        assert r.tool
        assert r.description
        assert r.severity
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_recommendation_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: 实现 recommendation_engine.py**

```python
"""Post-processing recommendation engine.

Generates actionable recommendations based on PrintabilityChecker results.
Maps issue types to specific tools (NX, Magics, Oqton) and actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PostProcessRecommendation:
    """A single post-processing recommendation."""

    action: str       # "thicken_wall", "add_support", "reorient", etc.
    tool: str         # "NX/Magics", "Oqton/Magics", etc.
    description: str
    severity: str     # "warning" | "error"


# Issue type → recommendation mapping
_ISSUE_RECOMMENDATIONS: dict[str, dict[str, str]] = {
    "thin_wall": {
        "action": "thicken_wall",
        "tool": "NX/Magics",
        "description": "增厚壁面至最小厚度要求。在 NX 或 Magics 中使用偏移面/加厚功能修复薄壁区域。",
    },
    "overhang": {
        "action": "add_support",
        "tool": "Oqton/Magics",
        "description": "添加支撑结构。在 Oqton 或 Magics 中自动生成树状支撑，减少悬垂角度。",
    },
    "small_feature": {
        "action": "enlarge_feature",
        "tool": "NX",
        "description": "放大过小特征至可打印尺寸。在 NX 中调整特征参数，确保最小特征大于喷嘴直径。",
    },
    "sharp_edge": {
        "action": "add_fillet",
        "tool": "NX",
        "description": "添加圆角消除尖锐边缘。在 NX 中对锐边添加 R0.5mm+ 的圆角，改善打印质量。",
    },
    "bridging": {
        "action": "add_support",
        "tool": "Oqton/Magics",
        "description": "添加桥接支撑。在 Oqton 中为跨距过大的桥接区域生成支撑。",
    },
}


def generate_recommendations(
    printability: dict[str, Any] | None,
) -> list[PostProcessRecommendation]:
    """Generate recommendations from printability check results.

    Args:
        printability: Output of PrintabilityChecker.check(), or None.

    Returns:
        List of actionable recommendations. Empty if no issues found.
    """
    if not printability:
        return []

    issues = printability.get("issues", [])
    if not issues:
        return []

    recommendations: list[PostProcessRecommendation] = []
    seen_actions: set[str] = set()

    for issue in issues:
        issue_type = issue.get("type", "")
        severity = issue.get("severity", "warning")
        mapping = _ISSUE_RECOMMENDATIONS.get(issue_type)

        if mapping and mapping["action"] not in seen_actions:
            seen_actions.add(mapping["action"])
            recommendations.append(
                PostProcessRecommendation(
                    action=mapping["action"],
                    tool=mapping["tool"],
                    description=mapping["description"],
                    severity=severity,
                )
            )

    return recommendations
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_recommendation_engine.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/core/recommendation_engine.py tests/test_recommendation_engine.py
git commit -m "feat(m2): add post-processing recommendation engine"
```

---

#### Task 11: 集成推荐引擎到 check_printability_node

**Files:**
- Modify: `backend/graph/nodes/postprocess.py:69-89`

**Step 1: 在 printability dispatch 后添加推荐生成**

在 `check_printability_node` 函数的 `_safe_dispatch("job.printability_ready", ...)` 之后，intercept block 之前，插入：

```python
    # Generate post-processing recommendations
    from backend.core.recommendation_engine import generate_recommendations

    new_recs = generate_recommendations(result)
    rec_dicts = [{"action": r.action, "tool": r.tool, "description": r.description, "severity": r.severity} for r in new_recs]

    # Merge with existing recommendations from analysis phase
    existing_recs = list(state.get("recommendations") or [])
    all_recs = existing_recs + rec_dicts

    await _safe_dispatch(
        "job.printability_checked",
        {"job_id": state["job_id"], "printability": result, "recommendations": all_recs},
    )
```

**Step 2: 更新 return statements 包含 recommendations**

所有 return 路径都应包含 `"recommendations": all_recs`（正常路径）。

对于 error-level intercept block 的 return（lines 83-87），也包含 recommendations：

```python
        if error_issues:
            error_msgs = "; ".join(issue.get("message", "") for issue in error_issues)
            return {
                "printability": result,
                "recommendations": all_recs,
                "error": f"Printability check failed: {error_msgs}",
                "status": "failed",
            }

    return {"printability": result, "recommendations": all_recs}
```

**Step 3: Run tests**

Run: `uv run pytest tests/test_graph_nodes_postprocess.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/graph/nodes/postprocess.py
git commit -m "feat(m2): integrate recommendation engine into check_printability_node"
```

---

#### Task 12: 持久化 recommendations 到 finalize_node

**Files:**
- Modify: `backend/graph/nodes/lifecycle.py:80-108`

**Step 1: 在 result_dict 组装中添加 recommendations**

在 `finalize_node` 中，在 `if state.get("matched_template"):` 块之后添加：

```python
    if state.get("recommendations"):
        result_dict["recommendations"] = state["recommendations"]
```

**Step 2: 在 completed event payload 中包含 recommendations**

在 `payload["printability"] = ...` 之后添加：

```python
        payload["recommendations"] = state.get("recommendations")
```

**Step 3: Run tests**

Run: `uv run pytest tests/ -k "finalize or lifecycle" -v`
Expected: PASS

**Step 4: Commit**

```bash
git add backend/graph/nodes/lifecycle.py
git commit -m "feat(m2): persist recommendations in finalize_node result"
```

---

#### Task 13: 写 postprocess 推荐集成测试

**Files:**
- Modify: `tests/test_graph_nodes_postprocess.py`

**Step 1: 添加推荐集成测试**

```python
class TestPrintabilityRecommendations:
    @pytest.mark.asyncio
    async def test_thin_wall_generates_recommendations(self, mock_dispatch):
        """check_printability_node should include recommendations for thin_wall issues."""
        with patch("backend.graph.nodes.postprocess._run_printability_check") as mock_check:
            mock_check.return_value = {
                "printable": True,
                "issues": [{"type": "thin_wall", "severity": "warning", "message": "Wall < 0.8mm"}],
            }
            result = await check_printability_node({
                "job_id": "test-1",
                "step_path": "/tmp/test.step",
            })
            assert "recommendations" in result
            assert len(result["recommendations"]) >= 1
            assert any(r["action"] == "thicken_wall" for r in result["recommendations"])

    @pytest.mark.asyncio
    async def test_no_issues_empty_recommendations(self, mock_dispatch):
        with patch("backend.graph.nodes.postprocess._run_printability_check") as mock_check:
            mock_check.return_value = {"printable": True, "issues": []}
            result = await check_printability_node({
                "job_id": "test-2",
                "step_path": "/tmp/test.step",
            })
            recs = result.get("recommendations", [])
            assert recs == []
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_graph_nodes_postprocess.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_graph_nodes_postprocess.py
git commit -m "test(m2): add recommendation integration tests for postprocess"
```

---

### Agent D: 拦截器注册表

**修改文件（独占）:**
- `backend/graph/interceptors.py`（新建）
- `backend/graph/builder.py`
- `tests/test_interceptor_registry.py`（新建）

#### Task 14: 创建 InterceptorRegistry

**Files:**
- Create: `backend/graph/interceptors.py`
- Create: `tests/test_interceptor_registry.py`

**Step 1: 写测试**

```python
"""Tests for InterceptorRegistry — build-time node insertion."""
import pytest

from backend.graph.interceptors import InterceptorRegistry


class TestInterceptorRegistry:
    def test_empty_registry(self):
        registry = InterceptorRegistry()
        assert registry.list_interceptors() == []

    def test_register_interceptor(self):
        registry = InterceptorRegistry()

        async def my_node(state):
            return {}

        registry.register("watermark", my_node, after="convert_preview")
        interceptors = registry.list_interceptors()
        assert len(interceptors) == 1
        assert interceptors[0]["name"] == "watermark"
        assert interceptors[0]["after"] == "convert_preview"

    def test_register_multiple(self):
        registry = InterceptorRegistry()

        async def node_a(state):
            return {}

        async def node_b(state):
            return {}

        registry.register("a", node_a, after="convert_preview")
        registry.register("b", node_b, after="a")
        assert len(registry.list_interceptors()) == 2

    def test_apply_no_interceptors_preserves_topology(self):
        """Empty registry should not modify the workflow."""
        from langgraph.graph import StateGraph
        from backend.graph.state import CadJobState

        registry = InterceptorRegistry()
        workflow = StateGraph(CadJobState)

        async def dummy(state):
            return {}

        workflow.add_node("convert_preview", dummy)
        workflow.add_node("check_printability", dummy)
        workflow.add_edge("convert_preview", "check_printability")

        # Apply should return without error
        registry.apply(workflow)

    def test_apply_inserts_node_between(self):
        from langgraph.graph import StateGraph
        from backend.graph.state import CadJobState

        registry = InterceptorRegistry()

        async def watermark_node(state):
            return {"watermark": True}

        registry.register("watermark", watermark_node, after="convert_preview")

        workflow = StateGraph(CadJobState)

        async def dummy(state):
            return {}

        workflow.add_node("convert_preview", dummy)
        workflow.add_node("check_printability", dummy)
        # Do NOT add the original edge — apply will handle wiring

        registry.apply(workflow)
        # Verify: watermark node should exist
        assert "watermark" in workflow.nodes
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_interceptor_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: 实现 InterceptorRegistry**

```python
"""InterceptorRegistry — build-time node insertion for the CAD pipeline.

Allows registering post-processing nodes that are inserted into the
StateGraph topology at build time. Interceptors are chained in registration
order within the same insertion point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class _InterceptorEntry:
    """A registered interceptor."""

    name: str
    node_fn: Callable[..., Awaitable[dict[str, Any]]]
    after: str  # node name to insert after


class InterceptorRegistry:
    """Registry for build-time pipeline node insertion.

    Usage::

        registry = InterceptorRegistry()
        registry.register("watermark", watermark_node, after="convert_preview")
        # In builder.py:
        registry.apply(workflow)
    """

    def __init__(self) -> None:
        self._entries: list[_InterceptorEntry] = []

    def register(
        self,
        name: str,
        node_fn: Callable[..., Awaitable[dict[str, Any]]],
        after: str,
    ) -> None:
        """Register a node to be inserted after *after* in the workflow."""
        self._entries.append(_InterceptorEntry(name=name, node_fn=node_fn, after=after))

    def list_interceptors(self) -> list[dict[str, str]]:
        """Return a summary of registered interceptors."""
        return [{"name": e.name, "after": e.after} for e in self._entries]

    def apply(self, workflow: Any) -> None:
        """Insert registered interceptors into the StateGraph workflow.

        For each interceptor registered after node X:
        1. Add the interceptor as a new node
        2. The caller (builder.py) is responsible for edge wiring

        This method only adds nodes; edge management is left to the builder
        to keep the registry decoupled from graph edge logic.
        """
        for entry in self._entries:
            if entry.name not in workflow.nodes:
                workflow.add_node(entry.name, entry.node_fn)
                logger.info("Interceptor '%s' added after '%s'", entry.name, entry.after)


# Module-level default registry (empty — interceptors registered at app startup)
default_registry = InterceptorRegistry()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_interceptor_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/graph/interceptors.py tests/test_interceptor_registry.py
git commit -m "feat(m2): add InterceptorRegistry for build-time node insertion"
```

---

#### Task 15: 集成 InterceptorRegistry 到 builder.py

**Files:**
- Modify: `backend/graph/builder.py:38-88`

**Step 1: 在 `_build_workflow()` 中集成注册表**

在 `_build_workflow()` 函数的节点和边定义之间，插入拦截器应用逻辑：

```python
def _build_workflow() -> StateGraph:
    """Construct the StateGraph topology (nodes + edges)."""
    from backend.graph.interceptors import default_registry

    workflow = StateGraph(CadJobState)

    # ── Core Nodes ── (unchanged)
    workflow.add_node("create_job", create_job_node)
    # ... (all existing add_node calls) ...

    # ── Apply registered interceptors ──
    default_registry.apply(workflow)

    # ── Edges ──
    # Build edge chain for convert_preview → ... → check_printability
    # accounting for interceptors inserted between them
    interceptors = default_registry.list_interceptors()
    post_convert_chain = [i["name"] for i in interceptors if i["after"] == "convert_preview"]

    workflow.add_edge(START, "create_job")
    # ... (all conditional edges unchanged) ...

    workflow.add_edge("generate_step_text", "convert_preview")
    workflow.add_edge("generate_step_drawing", "convert_preview")

    # Wire convert_preview → [interceptors] → check_printability
    if post_convert_chain:
        prev = "convert_preview"
        for node_name in post_convert_chain:
            workflow.add_edge(prev, node_name)
            prev = node_name
        workflow.add_edge(prev, "check_printability")
    else:
        workflow.add_edge("convert_preview", "check_printability")

    workflow.add_edge("generate_organic_mesh", "postprocess_organic")
    workflow.add_edge("postprocess_organic", "finalize")
    workflow.add_edge("check_printability", "finalize")
    workflow.add_edge("finalize", END)

    return workflow
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_graph_builder.py tests/test_interceptor_registry.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/graph/builder.py
git commit -m "feat(m2): wire InterceptorRegistry into _build_workflow"
```

---

#### Task 16: 写 builder 集成测试

**Files:**
- Modify: `tests/test_interceptor_registry.py`

**Step 1: 添加 builder 集成测试**

```python
class TestBuilderIntegration:
    def test_build_graph_with_no_interceptors(self):
        """Default empty registry should produce valid graph."""
        from backend.graph.builder import build_graph
        graph = build_graph()
        assert graph is not None

    def test_build_graph_nodes_unchanged(self):
        """Core node set should be preserved."""
        from backend.graph.builder import build_graph
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {"create_job", "analyze_intent", "analyze_vision", "confirm_with_user",
                    "generate_step_text", "generate_step_drawing", "convert_preview",
                    "check_printability", "finalize"}
        assert expected.issubset(node_names)
```

**Step 2: Run tests**

Run: `uv run pytest tests/test_interceptor_registry.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_interceptor_registry.py
git commit -m "test(m2): add builder integration tests for InterceptorRegistry"
```

---

## Phase 2: 集成验证 + 清理（串行，team lead）

### Task 17: 全量集成验证

**Step 1: 运行全量 Python 测试**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 2: TypeScript 类型检查**

Run: `cd frontend && npx tsc --noEmit`
Expected: PASS

**Step 3: 检查 vision_cad_pipeline.py 中的 _match_template 引用**

Run: `grep -rn "_match_template" backend/`

如果唯一调用方已是新代码中的 `TemplateEngine.find_matches`，则 `_match_template()` 可以删除。
如果仍有其他调用方，保留并标记 `# deprecated: use TemplateEngine.find_matches + rank_templates`。

**Step 4: Commit**

```bash
git commit --allow-empty -m "[impl] M2 Phase 2 complete: integration verified"
```
