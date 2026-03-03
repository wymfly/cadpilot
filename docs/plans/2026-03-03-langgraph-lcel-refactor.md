# LangGraph LCEL 重构实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 4 个 SequentialChain 替换为 LCEL Runnable，将 pipeline.py 编排逻辑内联到 LangGraph 节点，SmartRefiner 循环建模为子图。

**Architecture:** LCEL chain 工厂函数(`def build_*_chain() -> Runnable`)放在 `backend/graph/chains/`，Refiner 子图放在 `backend/graph/subgraphs/refiner.py`，节点层直接 `await chain.ainvoke()` 替代 `asyncio.to_thread()`。Best-of-N 改为 LLM 并发 + 执行串行。旧 Chain 标记 @deprecated 保留一个版本周期。

**Tech Stack:** LangChain LCEL (`prompt | llm.with_retry() | parser`)、LangGraph StateGraph 子图、asyncio.gather、SafeExecutor subprocess 隔离

**Design docs:**
- `openspec/changes/langgraph-lcel-refactor/design.md` — 5 ADR + 3 补充决策
- `openspec/changes/langgraph-lcel-refactor/specs/*/spec.md` — 4 个 spec 文件
- `openspec/changes/langgraph-lcel-refactor/tasks.md` — OpenSpec 任务清单

---

## 执行拓扑（Agent Team 并行感知）

```
T1(串行) → [T2 || T3](并行) → T4(串行) → [T5 || T6 || T7](并行) → T8(串行)
```

| Group | 描述 | 预期文件 | 依赖 |
|-------|------|---------|------|
| **T1** | LCEL Chain 基础设施 | `backend/graph/chains/*.py`, `tests/test_lcel_chains.py` | 无 |
| **T2** | Refiner 子图 | `backend/graph/subgraphs/refiner.py`, `tests/test_refiner_subgraph.py` | T1（read chains） |
| **T3** | Vision 节点迁移 | `backend/graph/nodes/analysis.py`, `tests/test_drawing_analyzer.py` | T1（read vision_chain） |
| **T4** | Generation 节点迁移 | `backend/graph/nodes/generation.py`, `tests/test_generation_nodes.py` | T1+T2+T3（read all） |
| **T5** | pipeline.py 清理 | `backend/pipeline/pipeline.py` | T4 |
| **T6** | 旧 Chain deprecated | `backend/core/{drawing_analyzer,code_generator,smart_refiner}.py`, `tests/test_smart_refiner.py` | T4 |
| **T7** | Resilience 测试 | `tests/test_llm_resilience.py` | T1+T3+T4 |
| **T8** | 验证与文档 | `CLAUDE.md` | T5+T6+T7 |

### 文件交叉矩阵

```
File                                           T1  T2  T3  T4  T5  T6  T7  T8
backend/graph/chains/__init__.py               W
backend/graph/chains/fix_chain.py              W
backend/graph/chains/compare_chain.py          W
backend/graph/chains/code_gen_chain.py         W
backend/graph/chains/vision_chain.py           W
backend/graph/subgraphs/__init__.py                W
backend/graph/subgraphs/refiner.py                 W       R
backend/graph/nodes/analysis.py                        W
backend/graph/nodes/generation.py                          W
backend/pipeline/pipeline.py                                   W
backend/core/drawing_analyzer.py                                   W
backend/core/code_generator.py                                     W
backend/core/smart_refiner.py                                      W
tests/test_lcel_chains.py                      W
tests/test_refiner_subgraph.py                     W
tests/test_drawing_analyzer.py                         W
tests/test_generation_nodes.py                             W
tests/test_smart_refiner.py                                        W
tests/test_llm_resilience.py                                           W
CLAUDE.md                                                                  W
```

**结论：** T2 和 T3 的 Write 集无交叉，可安全并行。T5/T6/T7 的 Write 集无交叉，可安全并行。

---

## Task 1: LCEL Chain 基础设施（串行）

> 创建 4 个 LCEL chain 工厂函数 + 测试，替代旧 SequentialChain。

**Files:**
- Create: `backend/graph/chains/__init__.py`
- Create: `backend/graph/chains/fix_chain.py`
- Create: `backend/graph/chains/compare_chain.py`
- Create: `backend/graph/chains/code_gen_chain.py`
- Create: `backend/graph/chains/vision_chain.py`
- Create: `tests/test_lcel_chains.py`

### Step 1: 创建模块目录结构

创建 `backend/graph/chains/__init__.py`:

```python
"""LCEL chain builders — sync factories returning Runnable objects.

Usage:
    chain = build_fix_chain()
    result = await chain.ainvoke({"code": ..., "fix_instructions": ...})
"""

from .code_gen_chain import build_code_gen_chain
from .compare_chain import build_compare_chain
from .fix_chain import build_fix_chain
from .vision_chain import build_vision_analysis_chain

__all__ = [
    "build_code_gen_chain",
    "build_compare_chain",
    "build_fix_chain",
    "build_vision_analysis_chain",
]
```

### Step 2: 实现 fix_chain.py

```python
"""LCEL chain for code fix (replaces SmartFixChain)."""
from __future__ import annotations

from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.smart_refiner import _FIX_CODE_PROMPT, _parse_code
from backend.infra.llm_config_manager import get_model_for_role


def build_fix_chain() -> Runnable:
    """Sync factory: build LCEL chain for code fix.

    Input:  {"code": str, "fix_instructions": str}
    Output: str | None  (fixed code or None if parse failed)
    """
    prompt = ChatPromptTemplate(
        input_variables=["code", "fix_instructions"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["code", "fix_instructions"],
                        template=_FIX_CODE_PROMPT,
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("refiner_coder").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_code({"text": text})
        return result["result"]

    return prompt | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True) | RunnableLambda(_parse)
```

### Step 3: 编写 fix_chain 测试

```python
# tests/test_lcel_chains.py
"""Tests for LCEL chain builders."""
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage


class TestFixChain:
    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_parses_code_block(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="```python\nresult = cq.Workplane('XY')\n```")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_fix_chain
        chain = build_fix_chain()
        result = chain.invoke({"code": "old_code", "fix_instructions": "fix it"})
        assert result == "result = cq.Workplane('XY')"

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_returns_none_for_empty(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="I don't know how to fix this")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_fix_chain
        chain = build_fix_chain()
        result = chain.invoke({"code": "old_code", "fix_instructions": "fix it"})
        assert result is None
```

**Run:**
```bash
uv run pytest tests/test_lcel_chains.py::TestFixChain -v
```
Expected: 2 PASS

### Step 4: 实现 compare_chain.py

```python
"""LCEL chain for VL comparison (replaces SmartCompareChain)."""
from __future__ import annotations

from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate
from langchain_core.prompts.image import ImagePromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.smart_refiner import (
    _COMPARE_PROMPT,
    _STRUCTURED_COMPARE_PROMPT,
    _extract_comparison,
)
from backend.core.vl_feedback import parse_vl_feedback
from backend.infra.llm_config_manager import get_model_for_role


def build_compare_chain(structured: bool = False) -> Runnable:
    """Sync factory: build LCEL chain for VL comparison.

    Input: {"drawing_spec": str, "code": str,
            "original_image_type": str, "original_image_data": str,
            "rendered_image_type": str, "rendered_image_data": str}
    Output: str | None  (comparison text or None if PASS)
    """
    compare_template = _STRUCTURED_COMPARE_PROMPT if structured else _COMPARE_PROMPT
    prompt = ChatPromptTemplate(
        input_variables=[
            "drawing_spec", "code",
            "original_image_type", "original_image_data",
            "rendered_image_type", "rendered_image_data",
        ],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["drawing_spec", "code"],
                        template=compare_template,
                    ),
                    ImagePromptTemplate(
                        input_variables=["original_image_type", "original_image_data"],
                        template={"url": "data:image/{original_image_type};base64,{original_image_data}"},
                    ),
                    ImagePromptTemplate(
                        input_variables=["rendered_image_type", "rendered_image_data"],
                        template={"url": "data:image/{rendered_image_type};base64,{rendered_image_data}"},
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("refiner_vl").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        if structured:
            feedback = parse_vl_feedback(text)
            if feedback and feedback.passed:
                return None
            return text
        result = _extract_comparison({"text": text})
        return result["result"]

    return prompt | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True) | RunnableLambda(_parse)
```

### Step 5: 编写 compare_chain 测试

追加到 `tests/test_lcel_chains.py`:

```python
class TestCompareChain:
    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_pass_uppercase(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="PASS")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_compare_chain
        chain = build_compare_chain(structured=False)
        result = chain.invoke({...})  # full input dict
        assert result is None

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_pass_lowercase(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="pass")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_compare_chain
        chain = build_compare_chain(structured=False)
        result = chain.invoke({...})
        assert result is None

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_fail_returns_text(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="问题1: 直径偏大\n预期: 50mm\n修改: 减小直径")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_compare_chain
        chain = build_compare_chain(structured=False)
        result = chain.invoke({...})
        assert "直径偏大" in result

    @patch("backend.graph.chains.compare_chain.parse_vl_feedback")
    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_structured_pass_uses_feedback_passed(self, mock_get_model, mock_parse):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content='{"verdict":"PASS","issues":[]}')
        mock_get_model.return_value.create_chat_model.return_value = mock_llm
        mock_feedback = MagicMock()
        mock_feedback.passed = True
        mock_parse.return_value = mock_feedback

        from backend.graph.chains import build_compare_chain
        chain = build_compare_chain(structured=True)
        result = chain.invoke({...})
        assert result is None
        mock_parse.assert_called_once()
```

**Run:**
```bash
uv run pytest tests/test_lcel_chains.py::TestCompareChain -v
```
Expected: 4 PASS

### Step 6: 实现 code_gen_chain.py

```python
"""LCEL chain for code generation (replaces CodeGeneratorChain)."""
from __future__ import annotations

from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.code_generator import _CODE_GEN_PROMPT, _parse_code
from backend.infra.llm_config_manager import get_model_for_role


def build_code_gen_chain() -> Runnable:
    """Sync factory: build LCEL chain for CadQuery code generation.

    Input:  {"modeling_context": str}
    Output: str | None  (generated code or None if parse failed)
    """
    prompt = ChatPromptTemplate(
        input_variables=["modeling_context"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["modeling_context"],
                        template=_CODE_GEN_PROMPT,
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("code_generator").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_code({"text": text})
        return result["result"]

    return prompt | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True) | RunnableLambda(_parse)
```

### Step 7: 编写 code_gen_chain 测试

```python
class TestCodeGenChain:
    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_parses_python_block(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        code = "import cadquery as cq\nresult = cq.Workplane('XY').box(10, 20, 30)"
        mock_llm.invoke.return_value = AIMessage(content=f"```python\n{code}\n```")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_code_gen_chain
        chain = build_code_gen_chain()
        result = chain.invoke({"modeling_context": "Build a box 10x20x30"})
        assert "cq.Workplane" in result
```

### Step 8: 实现 vision_chain.py

```python
"""LCEL chain for vision analysis (replaces DrawingAnalyzerChain)."""
from __future__ import annotations

from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate
from langchain_core.prompts.image import ImagePromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.drawing_analyzer import _DRAWING_ANALYSIS_PROMPT, _parse_drawing_spec
from backend.infra.llm_config_manager import get_model_for_role


def build_vision_analysis_chain() -> Runnable:
    """Sync factory: build LCEL chain for drawing analysis.

    Input:  {"image_type": str, "image_data": str}
    Output: DrawingSpec | None
    """
    prompt = ChatPromptTemplate(
        input_variables=["image_type", "image_data"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=[],
                        template=_DRAWING_ANALYSIS_PROMPT,
                    ),
                    ImagePromptTemplate(
                        input_variables=["image_type", "image_data"],
                        template={"url": "data:image/{image_type};base64,{image_data}"},
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("drawing_analyzer").create_chat_model()

    def _parse(ai_message):
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_drawing_spec({"text": text})
        return result.get("result")

    return prompt | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True) | RunnableLambda(_parse)
```

### Step 9: 编写 vision_chain 测试

```python
class TestVisionChain:
    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_parses_drawing_spec(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        json_text = '```json\n{"part_type": "rotational", "description": "test", ...}\n```'
        mock_llm.invoke.return_value = AIMessage(content=json_text)
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_vision_analysis_chain
        chain = build_vision_analysis_chain()
        result = chain.invoke({"image_type": "png", "image_data": "base64data"})
        assert result is not None  # DrawingSpec object

    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_returns_none_for_invalid_json(self, mock_get_model):
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_llm.invoke.return_value = AIMessage(content="I cannot analyze this image")
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains import build_vision_analysis_chain
        chain = build_vision_analysis_chain()
        result = chain.invoke({"image_type": "png", "image_data": "base64data"})
        assert result is None
```

### Step 10: 添加 prompt 等价性快照测试

```python
class TestPromptEquivalence:
    """Verify LCEL chains produce identical prompts to old SequentialChains."""

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_prompt_matches(self, mock_get_model):
        """Same input → same formatted prompt text between LCEL and old SmartFixChain."""
        # Build LCEL chain, extract prompt
        mock_llm = MagicMock()
        mock_llm.with_retry.return_value = mock_llm
        mock_get_model.return_value.create_chat_model.return_value = mock_llm

        from backend.graph.chains.fix_chain import build_fix_chain
        chain = build_fix_chain()
        # Extract prompt from the chain pipeline (first element)
        lcel_prompt = chain.first  # RunnableSequence.first is the prompt
        lcel_messages = lcel_prompt.invoke({"code": "test_code", "fix_instructions": "fix this"})

        # Build old chain, extract prompt
        from backend.core.smart_refiner import _FIX_CODE_PROMPT
        expected_text = _FIX_CODE_PROMPT.format(code="test_code", fix_instructions="fix this")
        actual_text = lcel_messages.messages[0].content
        assert expected_text == actual_text

    # Similar tests for compare_chain, code_gen_chain, vision_chain...
```

### Step 11: 运行全部 chain 测试并提交

**Run:**
```bash
uv run pytest tests/test_lcel_chains.py -v
```
Expected: ALL PASS

**Commit:**
```bash
git add backend/graph/chains/ tests/test_lcel_chains.py
git commit -m "feat(graph): add LCEL chain builders — fix, compare, codegen, vision

Sync factory functions (def build_*_chain() -> Runnable) replacing
4 SequentialChain classes with prompt | llm.with_retry() | parser.
Includes prompt equivalence snapshot tests."
```

---

## Task 2: Refiner 子图（与 T3 并行）

> 将 SmartRefiner Compare→Fix 循环建模为 LangGraph 子图。

**Files:**
- Create: `backend/graph/subgraphs/__init__.py`
- Create: `backend/graph/subgraphs/refiner.py`
- Create: `tests/test_refiner_subgraph.py`

**Depends on:** T1（import chain builders）

### Step 1: 定义 RefinerState + 状态映射函数

在 `backend/graph/subgraphs/refiner.py` 中：

```python
"""Refiner subgraph: Compare→Fix→Re-execute→Re-render cycle."""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.knowledge.part_types import DrawingSpec
from backend.models.pipeline_config import PipelineConfig


class RefinerState(TypedDict):
    code: str
    step_path: str
    drawing_spec: dict  # DrawingSpec.model_dump() at entry
    image_path: str
    round: int
    max_rounds: int
    verdict: str  # "pending" | "pass" | "fail" | "max_rounds_reached"
    static_notes: list[str]
    comparison_result: str | None
    rendered_image_path: str | None
    prev_score: float | None
    prev_code: str | None
    prev_step_path: str | None


def map_job_to_refiner(state: dict, config: dict) -> RefinerState:
    """CadJobState → RefinerState with DrawingSpec→dict conversion."""
    spec = state["drawing_spec"]
    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
    return RefinerState(
        code=state["generated_code"],
        step_path=state["step_path"],
        drawing_spec=spec.model_dump() if isinstance(spec, DrawingSpec) else spec,
        image_path=state["image_path"],
        round=0,
        max_rounds=pipeline_config.max_refinements,
        verdict="pending",
        static_notes=[],
        comparison_result=None,
        rendered_image_path=None,
        prev_score=None,
        prev_code=None,
        prev_step_path=None,
    )


def map_refiner_to_job(refiner_state: RefinerState) -> dict:
    """RefinerState → partial CadJobState update."""
    return {
        "generated_code": refiner_state["code"],
        "step_path": refiner_state["step_path"],
    }
```

### Step 2: 实现 static_diagnose 节点

```python
def static_diagnose(state: RefinerState, config: dict) -> dict:
    """Layer 1/2/2.5 diagnostics — no LLM calls."""
    from backend.core.validators import validate_bounding_box, validate_code_params, compare_topology, count_topology

    notes: list[str] = []
    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())

    try:
        spec = DrawingSpec(**state["drawing_spec"])
        result = validate_code_params(state["code"], spec)
        for m in result.mismatches:
            notes.append(f"参数不匹配: {m}")
    except Exception:
        pass

    # ... validate_bounding_box, optional compare_topology ...

    return {"static_notes": notes}
```

### Step 3: 实现 render_for_compare 节点

```python
def render_for_compare(state: RefinerState, config: dict) -> dict:
    """Render STEP → PNG for VL comparison."""
    import tempfile
    from backend.infra.render import render_and_export_image, render_multi_view
    from backend.infra.image import ImageData

    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
    step_path = state["step_path"]

    if pipeline_config.multi_view_render:
        # Multi-view with single-view fallback
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                view_paths = render_multi_view(step_path, tmpdir)
                if "isometric" in view_paths:
                    return {"rendered_image_path": view_paths["isometric"]}
                return {"rendered_image_path": next(iter(view_paths.values()))}
        except Exception:
            pass  # Fallback to single-view

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        render_and_export_image(step_path, f.name)
        return {"rendered_image_path": f.name}
```

### Step 4: 实现 vl_compare 节点

```python
async def vl_compare(state: RefinerState, config: dict) -> dict:
    """VL model comparison — the sole arbiter."""
    from backend.graph.chains import build_compare_chain
    from backend.infra.image import ImageData
    from backend.graph.nodes.lifecycle import _safe_dispatch

    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
    chain = build_compare_chain(structured=pipeline_config.structured_feedback)

    original = ImageData.load_from_file(state["image_path"])
    rendered = ImageData.load_from_file(state["rendered_image_path"])

    result = await chain.ainvoke({
        "drawing_spec": str(state["drawing_spec"]),
        "code": state["code"],
        "original_image_type": original.type,
        "original_image_data": original.data,
        "rendered_image_type": rendered.type,
        "rendered_image_data": rendered.data,
    })

    verdict = "pass" if result is None else "fail"
    await _safe_dispatch("job.refining", {
        "round": state["round"], "max_rounds": state["max_rounds"], "status": "comparing",
    })

    return {"comparison_result": result, "verdict": verdict}
```

### Step 5: 实现 coder_fix 节点（含 snapshot）

```python
async def coder_fix(state: RefinerState, config: dict) -> dict:
    """Fix code — snapshot BEFORE mutation."""
    from backend.graph.chains import build_fix_chain
    from backend.graph.nodes.lifecycle import _safe_dispatch

    # CRITICAL: snapshot current known-good code BEFORE mutation
    prev_code = state["code"]
    prev_step_path = state["step_path"]

    chain = build_fix_chain()
    fix_instructions = (state.get("comparison_result") or "") + "\n".join(state.get("static_notes", []))
    fixed_code = await chain.ainvoke({"code": state["code"], "fix_instructions": fix_instructions})

    await _safe_dispatch("job.refining", {
        "round": state["round"], "status": "fixing",
    })

    return {
        "code": fixed_code or state["code"],
        "prev_code": prev_code,
        "prev_step_path": prev_step_path,
    }
```

### Step 6: 实现 re_execute 节点（含 rollback + round++）

```python
def re_execute(state: RefinerState, config: dict) -> dict:
    """Execute fixed code, score, rollback if degraded, increment round."""
    from backend.infra.sandbox import SafeExecutor
    from backend.core.rollback import RollbackTracker
    from backend.pipeline.pipeline import _score_geometry
    from backend.core.candidate_scorer import score_candidate

    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
    spec = DrawingSpec(**state["drawing_spec"])

    executor = SafeExecutor()
    result = executor.execute(state["code"])

    updates: dict = {"round": state["round"] + 1}

    if result.success:
        compiled, volume_ok, bbox_ok, topology_ok = _score_geometry(state["step_path"], spec, pipeline_config)
        new_score = float(score_candidate(compiled=compiled, volume_ok=volume_ok, bbox_ok=bbox_ok, topology_ok=topology_ok))
        updates["prev_score"] = new_score

        # Rollback check
        if pipeline_config.rollback_on_degrade and state["prev_score"] is not None and new_score < state["prev_score"]:
            updates["code"] = state["prev_code"]
            updates["step_path"] = state["prev_step_path"]
            # Re-execute rolled-back code to restore STEP file
            executor.execute(state["prev_code"])

    return updates
```

### Step 7: 组装子图拓扑

```python
def _route_verdict(state: RefinerState) -> str:
    if state["verdict"] == "pass":
        return "end"
    if state["round"] >= state["max_rounds"]:
        return "max_reached"
    return "fix"


def build_refiner_subgraph():
    """Build the refiner subgraph: static → render → compare → [fix → execute → render → ...]."""
    graph = StateGraph(RefinerState)

    graph.add_node("static_diagnose", static_diagnose)
    graph.add_node("render_for_compare", render_for_compare)
    graph.add_node("vl_compare", vl_compare)
    graph.add_node("coder_fix", coder_fix)
    graph.add_node("re_execute", re_execute)

    graph.set_entry_point("static_diagnose")
    graph.add_edge("static_diagnose", "render_for_compare")
    graph.add_edge("render_for_compare", "vl_compare")
    graph.add_conditional_edges("vl_compare", _route_verdict, {
        "end": END,
        "max_reached": END,
        "fix": "coder_fix",
    })
    graph.add_edge("coder_fix", "re_execute")
    graph.add_edge("re_execute", "render_for_compare")  # Re-render after fix!

    return graph.compile()
```

### Step 8: 编写子图集成测试

`tests/test_refiner_subgraph.py`:

```python
"""Integration tests for refiner subgraph."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestRefinerSubgraph:
    @pytest.mark.asyncio
    async def test_pass_first_round(self):
        """VL says PASS on first round → exits immediately."""
        # Mock all chains, verify subgraph exits after static → render → compare(PASS)
        ...

    @pytest.mark.asyncio
    async def test_max_rounds_exit(self):
        """VL says FAIL for all rounds → exits with max_rounds_reached."""
        ...

    @pytest.mark.asyncio
    async def test_rollback_on_score_degradation(self):
        """Score drops after fix → rollback to prev_code."""
        ...

    @pytest.mark.asyncio
    async def test_comparison_result_available_in_coder_fix(self):
        """coder_fix can read comparison_result from vl_compare."""
        ...
```

### Step 9: 运行子图测试并提交

**Run:**
```bash
uv run pytest tests/test_refiner_subgraph.py -v
```

**Commit:**
```bash
git add backend/graph/subgraphs/ tests/test_refiner_subgraph.py
git commit -m "feat(graph): add refiner subgraph — Compare→Fix→Re-execute cycle

LangGraph StateGraph subgraph with RefinerState TypedDict,
rollback tracking, re-render between rounds, SSE events."
```

---

## Task 3: Vision 节点迁移（与 T2 并行）

> 重写 analyze_vision_node: LCEL chain 直接调用替代 asyncio.to_thread。

**Files:**
- Modify: `backend/graph/nodes/analysis.py:59-64,167-231`
- Modify: `tests/test_drawing_analyzer.py`

**Depends on:** T1（import vision_chain）

### Step 1: 重写 analyze_vision_node

删除 `_run_analyze_vision()` 同步包装函数。重写 `analyze_vision_node`：

```python
@register_node(name="analyze_vision", display_name="图纸分析",
    requires=["job_info"], produces=["drawing_spec"], input_types=["drawing"])
async def analyze_vision_node(state: CadJobState) -> dict[str, Any]:
    """Run VL model to extract DrawingSpec from uploaded image (with timeout)."""
    image_path = state.get("image_path")
    if not image_path:
        # ... error handling unchanged ...

    # Check result cache
    try:
        image_bytes = await asyncio.to_thread(Path(image_path).read_bytes)
        cached = _cost_optimizer.get_cached_result(image_bytes)
    except Exception:
        image_bytes = None
        cached = None

    if cached is not None:
        spec_dict, reasoning = cached
    else:
        try:
            # LCEL chain — direct async invocation, no to_thread wrapper
            from backend.graph.chains import build_vision_analysis_chain
            from backend.infra.image import ImageData

            image_data = ImageData.load_from_file(image_path)
            chain = build_vision_analysis_chain()
            spec = await asyncio.wait_for(
                chain.ainvoke({"image_type": image_data.type, "image_data": image_data.data}),
                timeout=LLM_TIMEOUT_S,
            )

            # OCR fusion (graceful degradation)
            if spec is not None:
                import base64
                raw_bytes = base64.b64decode(image_data.data)
                from backend.core.drawing_analyzer import fuse_ocr_with_spec
                try:
                    spec = fuse_ocr_with_spec(spec, raw_bytes)
                except Exception:
                    pass  # OCR failure is non-fatal

            spec_dict = spec.model_dump() if spec and hasattr(spec, "model_dump") else spec
            reasoning = None  # LCEL chain extracts spec directly

            if image_bytes is not None and spec_dict is not None:
                _cost_optimizer.cache_result(image_bytes, (spec_dict, reasoning))
        except Exception as exc:
            # ... error handling unchanged ...
    # ... rest unchanged ...
```

### Step 2: 删除 _run_analyze_vision 函数

从 `analysis.py` 中完全删除：

```python
# DELETE THIS FUNCTION:
def _run_analyze_vision(image_path: str) -> tuple:
    """Synchronous vision analysis — delegates to pipeline."""
    from backend.pipeline.pipeline import analyze_vision_spec
    spec, reasoning = analyze_vision_spec(image_path)
    spec_dict = spec.model_dump() if hasattr(spec, "model_dump") else spec
    return spec_dict, reasoning
```

### Step 3: 更新测试 mock 路径

```python
# tests/test_drawing_analyzer.py
# Before: mock DrawingAnalyzerChain.invoke or pipeline.analyze_vision_spec
# After: mock build_vision_analysis_chain return value

@patch("backend.graph.nodes.analysis.build_vision_analysis_chain")
async def test_vision_node_success(mock_build_chain):
    mock_chain = AsyncMock()
    mock_chain.ainvoke.return_value = MagicMock(model_dump=lambda: {"part_type": "rotational", ...})
    mock_build_chain.return_value = mock_chain
    # ... test logic ...
```

### Step 4: 运行 vision 节点测试

**Run:**
```bash
uv run pytest tests/test_drawing_analyzer.py tests/test_graph_nodes.py -v -k vision
```

**Commit:**
```bash
git add backend/graph/nodes/analysis.py tests/test_drawing_analyzer.py
git commit -m "refactor(nodes): vision node uses LCEL chain directly

Remove asyncio.to_thread(_run_analyze_vision) wrapper.
Direct await chain.ainvoke() with 60s timeout + OCR fusion."
```

---

## Task 4: Generation 节点迁移（串行，依赖 T1+T2+T3）

> 重写 generate_step_drawing_node: 内联编排逻辑 + refiner 子图集成。

**Files:**
- Modify: `backend/graph/nodes/generation.py:21-46,109-171`
- Create or modify: `tests/test_generation_nodes.py`

### Step 1: 创建 helper 函数骨架

```python
# backend/graph/nodes/generation.py

async def _orchestrate_drawing_generation(state: dict, config: dict) -> dict:
    """Orchestrate Stage 1.5→2→3→3.5→4→5 for drawing generation.

    Separated from node function for testability.
    Node handles state mapping, SSE, and exception wrapping.
    """
    from backend.core.modeling_strategist import ModelingStrategist
    from backend.core.api_whitelist import get_whitelist_prompt_section
    from backend.graph.chains import build_code_gen_chain
    from backend.graph.subgraphs.refiner import build_refiner_subgraph, map_job_to_refiner, map_refiner_to_job
    from backend.infra.sandbox import SafeExecutor
    from backend.core.validators import validate_step_geometry, cross_section_analysis
    from backend.knowledge.part_types import DrawingSpec
    from backend.models.pipeline_config import PipelineConfig
    from string import Template
    import tempfile

    pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
    spec = state.get("confirmed_spec") or state.get("drawing_spec")
    if isinstance(spec, dict):
        spec = DrawingSpec(**spec)

    step_path = state["step_path"]

    # Stage 1.5: Strategy selection (pure rule engine, no LLM)
    strategist = ModelingStrategist()
    context = strategist.select(spec)
    if pipeline_config.api_whitelist:
        context.strategy += "\n\n" + get_whitelist_prompt_section()

    # Stage 2: Code generation
    chain = build_code_gen_chain()
    modeling_input = {"modeling_context": context.to_prompt_text()}

    if pipeline_config.best_of_n > 1:
        # Phase 1: LLM concurrent
        codes = await asyncio.gather(
            *[chain.ainvoke(modeling_input) for _ in range(pipeline_config.best_of_n)],
            return_exceptions=True,
        )
        # Phase 2: Execute serial, score
        best_code, best_score = None, -1
        for raw_code in codes:
            if isinstance(raw_code, Exception) or raw_code is None:
                continue
            candidate_code = Template(raw_code).safe_substitute(output_filename=step_path)
            with tempfile.TemporaryDirectory() as tmpdir:
                executor = SafeExecutor(work_dir=tmpdir)
                exec_result = executor.execute(candidate_code)
                if exec_result.success:
                    from backend.pipeline.pipeline import _score_geometry
                    from backend.core.candidate_scorer import score_candidate
                    compiled, vol, bbox, topo = _score_geometry(step_path, spec, pipeline_config)
                    score = float(score_candidate(compiled=compiled, volume_ok=vol, bbox_ok=bbox, topology_ok=topo))
                    if score > best_score:
                        best_code, best_score = candidate_code, score
        code = best_code
    else:
        raw = await chain.ainvoke(modeling_input)
        code = Template(raw).safe_substitute(output_filename=step_path) if raw else None

    if code is None:
        return {"status": "failed", "failure_reason": "generation_error", "error": "Code generation failed"}

    # Stage 3: Execute
    executor = SafeExecutor()
    exec_result = executor.execute(code)

    # Stage 3.5: Geometry validation
    geo = validate_step_geometry(step_path)

    # Stage 4: Refiner subgraph
    refiner = build_refiner_subgraph()
    refiner_input = map_job_to_refiner(
        {"generated_code": code, "step_path": step_path, "drawing_spec": spec, "image_path": state["image_path"]},
        config,
    )
    refiner_result = await refiner.ainvoke(refiner_input, config=config)
    updates = map_refiner_to_job(refiner_result)

    # Stage 5: Post-checks
    if pipeline_config.cross_section_check:
        try:
            cross_section_analysis(step_path, spec)
        except Exception:
            pass

    return {
        "step_path": step_path,
        "generated_code": updates.get("generated_code", code),
    }
```

### Step 2: 重写 generate_step_drawing_node

```python
@register_node(name="generate_step_drawing", display_name="图纸→STEP生成",
    requires=["confirmed_params"], produces=["step_model"], input_types=["drawing"])
async def generate_step_drawing_node(state: CadJobState, config: dict = None) -> dict[str, Any]:
    """Generate STEP from confirmed DrawingSpec via LCEL chains + refiner subgraph."""
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {"_reasoning": {"skip": "idempotent, STEP already exists"}}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    await _safe_dispatch("job.generating", {
        "job_id": state["job_id"], "status": "generating",
        "message": "正在生成 STEP 模型（LCEL pipeline）",
    })

    try:
        result = await asyncio.wait_for(
            _orchestrate_drawing_generation({**state, "step_path": step_path}, config or {}),
            timeout=300.0,  # Heavyweight node: 300s
        )
    except asyncio.TimeoutError:
        await _safe_dispatch("job.failed", {
            "job_id": state["job_id"], "error": "图纸生成超时（300s）",
            "failure_reason": "timeout", "status": "failed",
        })
        return {"error": "图纸生成超时（300s）", "failure_reason": "timeout", "status": "failed"}
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_dispatch("job.failed", {
            "job_id": state["job_id"], "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    # Persist code
    code_text = result.get("generated_code", "")
    if code_text:
        (job_dir / "code.py").write_text(code_text, encoding="utf-8")

    return {
        "step_path": result.get("step_path", step_path),
        "generated_code": code_text or None,
        "status": "generating",
    }
```

### Step 3: 删除 _run_generate_from_spec 函数

从 `generation.py` 中完全删除旧的同步包装函数。

### Step 4: 编写 generation 节点测试

```python
# tests/test_generation_nodes.py
class TestGenerationNode:
    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation.build_refiner_subgraph")
    @patch("backend.graph.nodes.generation.build_code_gen_chain")
    async def test_single_path_generation(self, mock_codegen, mock_refiner):
        """Single-path: codegen → execute → refine → return."""
        ...

    @pytest.mark.asyncio
    async def test_best_of_n_concurrent_llm_serial_exec(self):
        """Best-of-N: N concurrent LLM calls, serial execution."""
        ...

    @pytest.mark.asyncio
    async def test_timeout_300s(self):
        """300s timeout on heavyweight node."""
        ...
```

### Step 5: 运行测试并提交

**Run:**
```bash
uv run pytest tests/test_generation_nodes.py -v
```

**Commit:**
```bash
git add backend/graph/nodes/generation.py tests/test_generation_nodes.py
git commit -m "refactor(nodes): generation node uses LCEL chains + refiner subgraph

Remove asyncio.to_thread(_run_generate_from_spec) wrapper.
Inline orchestration: strategy → codegen → execute → refine → post-check.
Best-of-N: concurrent LLM + serial SafeExecutor. 300s timeout."
```

---

## Task 5: pipeline.py 清理（与 T6/T7 并行）

> 删除已迁移的编排函数，保留工具函数。

**Files:**
- Modify: `backend/pipeline/pipeline.py`

**Depends on:** T4

### Step 1: 更新 analyze_and_generate_step

在 `analyze_and_generate_step()` 函数顶部添加注释，内部逻辑不变（仍调用旧 Chain 类）：

```python
def analyze_and_generate_step(
    image_filepath: str,
    output_filepath: str,
    ...
) -> str | None:
    """End-to-end pipeline: analyze → generate → refine.

    # TODO: migrate to LangGraph graph invocation (invoke CadJobStateGraph)
    Kept for CLI/benchmark backwards compatibility. Uses legacy Chain classes.
    """
    # ... existing implementation unchanged ...
```

### Step 2: 确认 analyze_and_generate_step 不依赖待删除函数

检查 `analyze_and_generate_step` 是否调用 `analyze_vision_spec` 或 `generate_step_from_spec`：
- 如果调用了 → 需要重写其内部实现（直接使用 Chain 类）
- 如果没有 → 安全删除

**实际情况：** `analyze_and_generate_step` 直接调用 `DrawingAnalyzerChain().invoke()` + `generate_step_from_spec()`。需要将 `generate_step_from_spec` 的调用替换为内联实现或保留该函数。

**决策：** 保留 `generate_step_from_spec` 供 `analyze_and_generate_step` 调用，仅删除 `analyze_vision_spec`（因为 `analyze_and_generate_step` 直接用 `DrawingAnalyzerChain`）。

### Step 3: 删除 analyze_vision_spec 和 _run_analyze_vision 引用

```python
# DELETE from pipeline.py:
def analyze_vision_spec(image_filepath: str) -> tuple[DrawingSpec | None, str | None]:
    ...
```

注意：`_run_analyze_vision` 在 `analysis.py` 中（T3 已删除），不在 pipeline.py 中。

### Step 4: 清理未使用的 import

运行 `uv run python -c "import backend.pipeline.pipeline"` 检查 import 错误，删除无用 import。

### Step 5: 运行全量测试

**Run:**
```bash
uv run pytest tests/ -v
```

**Commit:**
```bash
git add backend/pipeline/pipeline.py
git commit -m "refactor(pipeline): remove analyze_vision_spec, add TODO for graph migration

LangGraph nodes no longer call pipeline orchestration functions.
analyze_and_generate_step() kept for CLI/benchmark with TODO marker."
```

---

## Task 6: 旧 Chain deprecated 标记（与 T5/T7 并行）

> 标记 4 个旧 Chain 类为 deprecated。

**Files:**
- Modify: `backend/core/drawing_analyzer.py`
- Modify: `backend/core/code_generator.py`
- Modify: `backend/core/smart_refiner.py`
- Modify: `tests/test_smart_refiner.py`

**Depends on:** T4

### Step 1: 添加 @deprecated 装饰器

```python
# backend/core/drawing_analyzer.py
import warnings

class DrawingAnalyzerChain(SequentialChain):
    """@deprecated: Use backend.graph.chains.build_vision_analysis_chain() instead."""

    def __init__(self):
        warnings.warn(
            "DrawingAnalyzerChain is deprecated. Use build_vision_analysis_chain() from backend.graph.chains.",
            DeprecationWarning,
            stacklevel=2,
        )
        # ... existing __init__ ...
```

同样处理 `CodeGeneratorChain`、`SmartCompareChain`、`SmartFixChain`。

### Step 2: 更新 test_smart_refiner.py mock

将 mock 从旧 Chain 改为 LCEL chain mock（如果测试仍需要测 SmartRefiner 旧类，保留 DeprecationWarning 过滤）。

### Step 3: 运行全量测试

**Run:**
```bash
uv run pytest tests/ -v -W default::DeprecationWarning
```

**Commit:**
```bash
git add backend/core/drawing_analyzer.py backend/core/code_generator.py backend/core/smart_refiner.py tests/test_smart_refiner.py
git commit -m "chore: mark 4 legacy Chain classes as deprecated

DrawingAnalyzerChain, CodeGeneratorChain, SmartCompareChain, SmartFixChain
→ use backend.graph.chains.build_*_chain() instead."
```

---

## Task 7: Resilience 测试补充（与 T5/T6 并行）

> 验证 retry、timeout、fallback 机制。

**Files:**
- Create: `tests/test_llm_resilience.py`

**Depends on:** T1 + T3 + T4

### Step 1: 编写 retry 测试

```python
"""Resilience tests for LCEL chains and LangGraph nodes."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage


class TestRetry:
    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_retries_on_rate_limit(self, mock_get_model):
        """LLM fails twice with RateLimitError, succeeds on 3rd → transparent retry."""
        mock_llm = MagicMock()
        # with_retry should be configured; test that the chain builder sets it up
        from backend.graph.chains import build_fix_chain
        chain = build_fix_chain()
        # Verify .with_retry() was called
        mock_get_model.return_value.create_chat_model.return_value.with_retry.assert_called_once()
```

### Step 2: 编写 timeout 测试

```python
class TestTimeout:
    @pytest.mark.asyncio
    async def test_generation_node_timeout_300s(self):
        """mock chain.ainvoke hangs > 300s → TimeoutError → failed state."""
        ...

    @pytest.mark.asyncio
    async def test_vision_node_timeout_60s(self):
        """mock chain.ainvoke hangs > 60s → TimeoutError → failed state."""
        ...
```

### Step 3: 运行 resilience 测试

**Run:**
```bash
uv run pytest tests/test_llm_resilience.py -v
```

**Commit:**
```bash
git add tests/test_llm_resilience.py
git commit -m "test: add LLM resilience tests — retry, timeout, fallback

Verify .with_retry() on all LCEL chains, 60s/300s tiered timeout,
typed failure_reason in SSE payloads."
```

---

## Task 8: 验证与文档（串行，最终）

> Grep 验证 + TypeScript 检查 + 全量测试 + 文档更新。

**Files:**
- Modify: `CLAUDE.md`

**Depends on:** T5 + T6 + T7

### Step 1: Grep 验证

```bash
# 无 asyncio.to_thread 调用 vision/generation 同步函数
git grep "to_thread.*_run_analyze\|to_thread.*_run_generate"
# 期望: 0 结果

# LangGraph 节点不直接 import SequentialChain
git grep "from.*SequentialChain\|import.*SequentialChain" backend/graph/
# 期望: 0 结果

# 所有 chain builder 为同步工厂
git grep "async def build_.*_chain" backend/graph/chains/
# 期望: 0 结果
```

### Step 2: TypeScript 编译检查

```bash
cd frontend && npx tsc --noEmit
```
期望: 无错误（后端重构不影响前端）

### Step 3: 更新 CLAUDE.md 架构描述

在 CLAUDE.md 的 `## 架构` 部分添加新的调用栈描述：

```markdown
### V2 管道（重构后）

```
图纸(PNG/JPG)
  → analyze_vision_node: build_vision_analysis_chain().ainvoke() → DrawingSpec
  → generate_step_drawing_node:
      → Stage 1.5: ModelingStrategist.select() (规则引擎)
      → Stage 2: build_code_gen_chain().ainvoke() (LCEL, 支持 Best-of-N 并发)
      → Stage 3: SafeExecutor.execute() → STEP
      → Stage 3.5: validate_step_geometry()
      → Stage 4: refiner_subgraph.ainvoke() (LangGraph 子图)
          ├─ static_diagnose (参数+包围盒+拓扑诊断)
          ├─ render_for_compare → vl_compare (唯一裁判)
          └─ coder_fix → re_execute (rollback 保护)
      → Stage 5: cross_section_analysis()
```
```

### Step 4: 全量测试最终确认

**Run:**
```bash
uv run pytest tests/ -v
```
期望: ALL PASS

### Step 5: 最终提交

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md architecture for LCEL chain + refiner subgraph"
```

---

## 附录：关键实现参考

### 旧 Chain 的 prompt/parser 函数位置

| Chain | Prompt 常量 | Parser 函数 | 文件 |
|-------|------------|------------|------|
| SmartFixChain | `_FIX_CODE_PROMPT` | `_parse_code()` | `backend/core/smart_refiner.py:111-144` |
| SmartCompareChain | `_COMPARE_PROMPT` / `_STRUCTURED_COMPARE_PROMPT` | `_extract_comparison()` | `backend/core/smart_refiner.py:29-152` |
| CodeGeneratorChain | `_CODE_GEN_PROMPT` | `_parse_code()` | `backend/core/code_generator.py` |
| DrawingAnalyzerChain | `_DRAWING_ANALYSIS_PROMPT` | `_parse_drawing_spec()` | `backend/core/drawing_analyzer.py:17-90` |

### 旧 Chain 的 prep_inputs() 适配

| Chain | 旧 prep_inputs | 新适配方式 |
|-------|---------------|----------|
| DrawingAnalyzerChain | `ImageData → {"image_type", "image_data"}` | 节点层: `{"image_type": img.type, "image_data": img.data}` |
| CodeGeneratorChain | `ModelingContext → {"modeling_context": str}` | 节点层: `{"modeling_context": ctx.to_prompt_text()}` |
| SmartCompareChain | 手动构建 6 字段 dict | 子图 vl_compare 节点构建 |
| SmartFixChain | `{"code", "fix_instructions"}` | 子图 coder_fix 节点构建 |

### PipelineConfig 关键字段

```python
pipeline_config = config.get("configurable", {}).get("pipeline_config", PipelineConfig())
# .max_refinements → refiner max_rounds (default: 3)
# .structured_feedback → compare chain structured mode (default: True)
# .topology_check → static_diagnose topology (default: True)
# .multi_view_render → render multi vs single view (default: True)
# .rollback_on_degrade → rollback tracker enabled (default: True)
# .best_of_n → concurrent LLM count (default: 1 fast, 3 balanced)
# .api_whitelist → inject API whitelist to strategy (default: True)
# .cross_section_check → Stage 5 post-check (default: False)
```
