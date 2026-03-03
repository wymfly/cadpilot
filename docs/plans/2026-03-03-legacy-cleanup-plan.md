# 遗留代码清理实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 移除 v1/v2/v3 历史版本标签和死代码，统一为纯 LangGraph 双管道架构。

**Architecture:** 删除 `cadpilot/` 兼容包和 `backend/v1/`，统一构建器为 `builder.py`（原 `builder_new.py`），迁移所有 import 路径，清理版本标签和旧入口脚本。

**Tech Stack:** Python, LangGraph, pytest

---

### Task 1: 删除 `cadpilot/` 包 + `backend/v1/` + 旧入口脚本

**Files:**
- Delete: `cadpilot/` (整个目录)
- Delete: `backend/v1/` (整个目录)
- Delete: `scripts/app.py`
- Delete: `scripts/cli.py`
- Delete: `start.sh`
- Rename: `scripts/start-v3.sh` → `scripts/start.sh`
- Delete: `tests/test_import_compat.py`

**Step 1: 删除 cadpilot/ 整包**

```bash
rm -rf cadpilot/
```

这个目录包含 27 个 .py 文件 + knowledge/ 子包，全部是 `backend/` 的兼容 shim。

**Step 2: 删除 backend/v1/**

```bash
rm -rf backend/v1/
```

包含 `CadCodeGeneratorChain`、`CadCodeRefinerChain`，V1 最旧实现。

**Step 3: 删除旧入口脚本**

```bash
rm scripts/app.py scripts/cli.py
rm start.sh
```

- `scripts/app.py` — Streamlit UI，已被 React 前端取代
- `scripts/cli.py` — 旧 CLI，使用 `from cadpilot import ...`
- `start.sh` — Streamlit 启动脚本

**Step 4: 重命名 start-v3.sh → start.sh**

```bash
mv scripts/start-v3.sh scripts/start.sh
```

**Step 5: 删除 test_import_compat.py**

```bash
rm tests/test_import_compat.py
```

该测试验证 `cadpilot` 包兼容 shim，`cadpilot/` 删除后无意义。保留其中 `test_backend_*` 测试项——但这些测试实际上在其他测试文件中已有覆盖，无需单独迁移。

**Step 6: 运行测试确认删除未破坏其他测试**

Run: `uv run pytest tests/ -x -q --tb=line 2>&1 | tail -20`

此时预期部分测试会 FAIL（引用了 `cadpilot.xxx` 或 `backend.v1`），这些会在后续 Task 修复。验证**无意外的失败**。

**Step 7: Commit**

```bash
git add -A
git commit -m "chore: remove cadpilot/ compat shim, backend/v1/, old scripts"
```

---

### Task 2: 迁移 import 路径（`from cadpilot.xxx` → `from backend.xxx`）

**Files:**
- Modify: `tests/test_knowledge_base.py`
- Modify: `tests/test_knowledge_expansion.py`
- Modify: `tests/test_modeling_strategist.py`
- Modify: `tests/test_feature_model.py`
- Modify: `tests/test_smart_refiner.py`
- Modify: `tests/test_drawing_analyzer.py`
- Modify: `tests/test_validators.py`
- Modify: `tests/test_vector_retrieval.py`
- Modify: `backend/graph/nodes/generation.py:38`

**Step 1: 批量替换 import 路径**

每个文件中的替换规则：

| 旧路径 | 新路径 |
|--------|--------|
| `cadpilot.knowledge.examples` | `backend.knowledge.examples` |
| `cadpilot.knowledge.part_types` | `backend.knowledge.part_types` |
| `cadpilot.v2.modeling_strategist` | `backend.core.modeling_strategist` |
| `cadpilot.v2.smart_refiner` | `backend.core.smart_refiner` |
| `cadpilot.v2.drawing_analyzer` | `backend.core.drawing_analyzer` |
| `cadpilot.v2.validators` | `backend.core.validators` |

具体文件修改：

`tests/test_knowledge_base.py`:
```python
# 旧
from cadpilot.knowledge.examples import (
from cadpilot.knowledge.examples.bracket import BRACKET_EXAMPLES
...
from cadpilot.knowledge.part_types import PartType

# 新
from backend.knowledge.examples import (
from backend.knowledge.examples.bracket import BRACKET_EXAMPLES
...
from backend.knowledge.part_types import PartType
```

`tests/test_knowledge_expansion.py`:
```python
# 旧
from cadpilot.knowledge.examples import EXAMPLES_BY_TYPE, get_tagged_examples
from cadpilot.knowledge.part_types import PartType

# 新
from backend.knowledge.examples import EXAMPLES_BY_TYPE, get_tagged_examples
from backend.knowledge.part_types import PartType
```

`tests/test_modeling_strategist.py`:
```python
# 旧
from cadpilot.knowledge.part_types import (
from cadpilot.v2.modeling_strategist import ModelingContext, ModelingStrategist
from cadpilot.v2.modeling_strategist import _extract_features_from_spec
from cadpilot.v2.modeling_strategist import _jaccard

# 新
from backend.knowledge.part_types import (
from backend.core.modeling_strategist import ModelingContext, ModelingStrategist
from backend.core.modeling_strategist import _extract_features_from_spec
from backend.core.modeling_strategist import _jaccard
```

`tests/test_feature_model.py`:
```python
# 旧
from cadpilot.knowledge.part_types import (
from cadpilot.v2.modeling_strategist import _extract_features_from_spec

# 新
from backend.knowledge.part_types import (
from backend.core.modeling_strategist import _extract_features_from_spec
```

`tests/test_smart_refiner.py`:
```python
# 旧
from cadpilot.knowledge.part_types import (
from cadpilot.v2.smart_refiner import SmartRefiner

# 新
from backend.knowledge.part_types import (
from backend.core.smart_refiner import SmartRefiner
```

`tests/test_drawing_analyzer.py`:
```python
# 旧
from cadpilot.v2.drawing_analyzer import _parse_drawing_spec

# 新
from backend.core.drawing_analyzer import _parse_drawing_spec
```

`tests/test_validators.py`:
```python
# 旧
from cadpilot.knowledge.part_types import (
from cadpilot.v2.validators import (
from cadpilot.v2.validators import validate_step_geometry, GeometryResult

# 新
from backend.knowledge.part_types import (
from backend.core.validators import (
from backend.core.validators import validate_step_geometry, GeometryResult
```

`tests/test_vector_retrieval.py`:
```python
# 旧
from cadpilot.v2.modeling_strategist import ModelingContext, ModelingStrategist

# 新
from backend.core.modeling_strategist import ModelingContext, ModelingStrategist
```

`backend/graph/nodes/generation.py:38`:
```python
# 旧
from cadpilot.knowledge.part_types import DrawingSpec

# 新
from backend.knowledge.part_types import DrawingSpec
```

**Step 2: 验证无遗留 cadpilot 引用**

Run: `git grep -r "from cadpilot" -- "*.py"`
Expected: 0 结果

**Step 3: 运行受影响测试**

Run: `uv run pytest tests/test_knowledge_base.py tests/test_knowledge_expansion.py tests/test_modeling_strategist.py tests/test_feature_model.py tests/test_smart_refiner.py tests/test_drawing_analyzer.py tests/test_validators.py tests/test_vector_retrieval.py -v`
Expected: 全部 PASS

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: migrate imports from cadpilot.xxx to backend.xxx"
```

---

### Task 3: pipeline.py 移除 V1 降级路径

**Files:**
- Modify: `backend/pipeline/pipeline.py`
- Modify: `backend/pipeline/sse_bridge.py` (清理版本注释)

**Step 1: 移除 V1 import 和 V1 函数**

在 `backend/pipeline/pipeline.py` 中：

删除 import（第 30-31 行）：
```python
# 删除这两行
from ..v1.cad_code_generator import CadCodeGeneratorChain
from ..v1.cad_code_refiner import CadCodeRefinerChain
```

删除 `generate_step_from_2d_cad_image` 函数（第 45-91 行）——整个函数是 V1 管道入口。

修改 `analyze_and_generate_step` 函数（第 556-599 行），移除 V1 降级：
```python
# 旧代码（第 580-584 行）
    if spec is None:
        logger.error("[V2] Drawing analysis failed, falling back to v1 pipeline")
        num_ref = num_refinements if num_refinements is not None else 3
        return generate_step_from_2d_cad_image(
            image_filepath, output_filepath, num_ref, model_type="qwen"
        )

# 新代码
    if spec is None:
        logger.error("Drawing analysis failed")
        return None
```

删除底部的 V1 兼容别名（第 602-605 行）：
```python
# 删除这些行
analyze_drawing = analyze_vision_spec
generate_from_drawing_spec = generate_step_from_spec
generate_step_v2 = analyze_and_generate_step
```

**Step 2: 清理版本注释**

在 `pipeline.py` 中，所有 `[V2]` 日志前缀替换为无前缀：
```python
# 旧
logger.info("[V2] Stage 1: Analyzing drawing with VL model...")
# 新
logger.info("Stage 1: Analyzing drawing with VL model...")
```

在 `sse_bridge.py` 中，更新模块 docstring：
```python
# 旧
"""PipelineBridge: V2 管道回调 → SSE 事件队列的桥接层。

将 generate_step_v2 的 on_spec_ready / on_progress 回调映射为
...

# 新
"""PipelineBridge: 管道回调 → SSE 事件队列的桥接层。

将 analyze_and_generate_step 的 on_spec_ready / on_progress 回调映射为
...
```

同时更新 `sse_bridge.py` 中的用法示例注释（将 `generate_step_v2` 替换为 `analyze_and_generate_step`）。

**Step 3: 检查是否有其他引用 V1 函数**

Run: `git grep -rn "generate_step_from_2d_cad_image\|generate_step_v2\|CadCodeGeneratorChain\|CadCodeRefinerChain" -- "*.py" | grep -v "^tests/test_import_compat"`
Expected: 只剩 `backend/pipeline/pipeline.py` 中保留的函数定义（`analyze_and_generate_step`），不再有 V1 引用。

**Step 4: 运行 pipeline 相关测试**

Run: `uv run pytest tests/test_sse_bridge.py tests/test_v1_pipeline_integration.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove V1 fallback path from pipeline.py"
```

---

### Task 4: 统一构建器（删除 builder_legacy + 重命名 builder_new）

**Files:**
- Delete: `backend/graph/builder_legacy.py`
- Delete: `backend/graph/builder.py` (旧 wrapper)
- Rename: `backend/graph/builder_new.py` → `backend/graph/builder.py`
- Modify: `backend/graph/__init__.py`
- Modify: `backend/graph/routing.py`
- Modify: `backend/graph/nodes/organic.py`
- Modify: `tests/test_graph_builder.py`
- Modify: `tests/test_builder_new.py` → rename to `tests/test_builder.py`
- Modify: `tests/test_organic_nodes.py`
- Modify: `tests/test_generate_raw_mesh.py`
- Modify: `tests/test_phase2_integration.py`
- Modify: `tests/test_mesh_healer.py`
- Modify: `tests/test_interceptor_registry.py`
- Modify: `tests/test_dual_channel_e2e.py`

**Step 1: 删除 builder_legacy.py 和旧 builder.py wrapper**

```bash
rm backend/graph/builder_legacy.py
rm backend/graph/builder.py
```

**Step 2: 重命名 builder_new.py → builder.py**

```bash
mv backend/graph/builder_new.py backend/graph/builder.py
```

**Step 3: 更新 builder.py 的模块 docstring**

```python
# 旧
"""New PipelineBuilder — dynamically generates StateGraph from resolved pipeline.

This file coexists with the legacy builder.py.  Activation is controlled by
the USE_NEW_BUILDER environment variable (default OFF).
"""

# 新
"""PipelineBuilder — dynamically generates StateGraph from resolved pipeline."""
```

**Step 4: 简化 `backend/graph/__init__.py`**

将整个文件替换为：

```python
"""LangGraph CAD Job orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.graph.builder import build_graph as build_graph
    from backend.graph.builder import get_compiled_graph as get_compiled_graph

__all__ = ["build_graph", "get_compiled_graph"]


def __getattr__(name: str):
    """Lazy import to avoid eagerly loading langgraph at module import time."""
    if name in __all__:
        from backend.graph import builder

        if name == "get_compiled_graph":
            return builder.get_compiled_graph_new
        elif name == "build_graph":
            from backend.graph.discovery import discover_nodes
            from backend.graph.registry import registry
            from backend.graph.resolver import DependencyResolver

            def _build_graph():
                discover_nodes()
                from backend.graph.interceptors import default_registry
                resolved = DependencyResolver.resolve_all(registry, {})
                return builder.PipelineBuilder().build(
                    resolved, interceptor_registry=default_registry,
                ).compile()

            return _build_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Step 5: 删除 routing.py 中 `route_after_organic_mesh`**

`route_after_organic_mesh` 仅被 `builder_legacy.py` 使用。删除该函数（第 13-21 行）。同时删除 `builder_legacy.py` 中对它的 import（已随文件删除）。

**Step 6: 删除 organic.py 中 deprecated 函数**

删除 `generate_organic_mesh_node`（第 112-208 行）和 `postprocess_organic_node`（第 227-383 行）。

保留 `analyze_organic_node`（第 37-104 行）和 `_load_reference_image`（第 211-219 行，仍可能被其他代码使用）和 `_safe_update_job`。

**Step 7: 更新所有引用 `builder_new` 的测试文件**

全局替换 `from backend.graph.builder_new import` → `from backend.graph.builder import`：

涉及文件：
- `tests/test_builder_new.py` — 重命名为 `tests/test_builder.py`，并更新内部 import 和 patch 路径
- `tests/test_graph_builder.py` — 删除 `TestBuilderSwitch` 类（测试 `USE_NEW_BUILDER` 双轨切换），更新 `TestBuildGraph.test_graph_has_expected_nodes` 移除 `generate_organic_mesh` 和 `postprocess_organic`
- `tests/test_mesh_healer.py` — 替换 `builder_new` → `builder`
- `tests/test_interceptor_registry.py` — 替换 `builder_new` → `builder`
- `tests/test_phase2_integration.py` — 替换 `builder_new` → `builder`
- `tests/test_dual_channel_e2e.py` — 替换 `builder_new` → `builder`

`tests/test_builder_new.py` 重命名：
```bash
mv tests/test_builder_new.py tests/test_builder.py
```

在 `tests/test_builder.py` 中，全局替换：
- `from backend.graph.builder_new import` → `from backend.graph.builder import`
- `"backend.graph.builder_new._safe_dispatch"` → `"backend.graph.builder._safe_dispatch"`

**Step 8: 更新 test_graph_builder.py**

删除 `TestBuilderSwitch` 类整体（第 53-119 行，测试 `USE_NEW_BUILDER` 双轨），它不再有意义。

更新 `TestBuildGraph.test_graph_has_expected_nodes`：移除 `"generate_organic_mesh"` 和 `"postprocess_organic"`，因为它们已被删除。添加新管道节点如 `"generate_raw_mesh"`, `"mesh_healer"` 等。

更新 `TestTraceMerge.test_fallback_trace_merged_into_node_trace`：替换 `builder_new` → `builder`。

**Step 9: 更新 test_organic_nodes.py**

删除所有 `generate_organic_mesh_node` 和 `postprocess_organic_node` 相关的测试类/方法。保留 `analyze_organic_node` 的测试。

更新 import：
```python
# 旧
from backend.graph.nodes.organic import (
    analyze_organic_node,
    generate_organic_mesh_node,
    postprocess_organic_node,
)

# 新
from backend.graph.nodes.organic import analyze_organic_node
```

**Step 10: 更新 test_generate_raw_mesh.py**

删除 `TestLegacyAdapter` 类（第 983-1064 行，测试 `generate_organic_mesh_node` 兼容性和 `builder_legacy.py` 导入）。

**Step 11: 更新 test_phase2_integration.py**

删除 `TestDeprecationWarnings` 类（第 454-468 行，测试 `postprocess_organic_node` 发 DeprecationWarning）。

替换 `builder_new` → `builder`。

**Step 12: 验证无遗留引用**

Run: `git grep -rn "builder_legacy\|builder_new\|USE_NEW_BUILDER\|generate_organic_mesh_node\|postprocess_organic_node" -- "*.py"`
Expected: 0 结果（除了 `generate_raw_mesh.py` 中的注释 "Replaces the monolithic generate_organic_mesh_node"，可保留作为历史说明，也可清理）

**Step 13: 运行完整测试套件**

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

**Step 14: Commit**

```bash
git add -A
git commit -m "refactor: unify builder, remove legacy builder + deprecated organic nodes"
```

---

### Task 5: 清理版本标签 + pyproject.toml + CLAUDE.md

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`
- Modify: `backend/graph/nodes/generation.py` (注释)
- Modify: `backend/graph/nodes/mesh_scale.py` (注释)
- Modify: `backend/graph/nodes/generate_raw_mesh.py` (注释)
- Modify: `tests/test_v1_pipeline_integration.py` → rename to `tests/test_pipeline_integration.py`
- Modify: `backend/pipeline/pipeline.py` (函数/注释)
- Modify: `backend/graph/resolver.py` (注释)
- Modify: `backend/graph/registry.py` (注释)

**Step 1: 更新 pyproject.toml**

移除版本注释和 streamlit 依赖：
```toml
# 旧
dependencies = [
    # V2 existing (pinned to 0.3.x — V2 code uses langchain.chains etc.)
    "langchain>=0.3.18,<1.0",
    ...
    "streamlit>=1.37.1",
    ...
    # V3 new
    "fastapi>=0.115.0",
    ...
]

# 新
dependencies = [
    # LangChain
    "langchain>=0.3.18,<1.0",
    ...
    # 移除 streamlit
    # FastAPI
    "fastapi>=0.115.0",
    ...
]
```

更新 wheel packages（移除 cadpilot）：
```toml
# 旧
[tool.hatch.build.targets.wheel]
packages = ["cadpilot", "backend"]

# 新
[tool.hatch.build.targets.wheel]
packages = ["backend"]
```

**Step 2: 重命名 test_v1_pipeline_integration.py**

```bash
mv tests/test_v1_pipeline_integration.py tests/test_pipeline_integration.py
```

该文件测试的是 PipelineBridge、SSE 事件、HITL 确认、Job 生命周期——与 V1 无关，名字误导。更新文件顶部注释：

```python
# 旧
"""Tests for Task #3: 后端管道集成。

# 新
"""Tests for pipeline integration: PipelineBridge, SSE events, HITL flow.
```

**Step 3: 清理代码中的版本标签注释**

`backend/graph/nodes/mesh_scale.py:3`:
```python
# 旧
"""...
New-mode node (NodeContext signature) for builder_new.py only.
"""

# 新
"""..."""  # 移除 builder_new 引用
```

`backend/graph/nodes/generate_raw_mesh.py:3`:
```python
# 旧
"""...
Replaces the monolithic generate_organic_mesh_node with a strategy-based
...
"""

# 新（可保留功能描述，但移除对旧节点的引用或简化）
```

`backend/graph/resolver.py:26`:
```python
# 旧
"""Output of DependencyResolver — everything PipelineBuilder needs."""

# 这个没问题，PipelineBuilder 仍然存在，保留
```

`backend/pipeline/pipeline.py` 中的函数名和注释：
- 移除所有 `[V2]` 日志前缀（在 Task 3 可能已部分处理）
- 更新 `# V2 pipeline entry point` 注释为 `# Pipeline entry point`

**Step 4: 更新 CLAUDE.md**

更新项目结构部分：
- 移除 `cadpilot/` 目录描述
- 移除 V1/V2/V3 版本标签
- 更新"当前状态"描述
- 更新"架构"部分
- 移除 "V1 → V2 降级" 注意事项
- 更新验证命令

**Step 5: 最终验证**

Run: `git grep -rn "from cadpilot\|USE_NEW_BUILDER\|builder_legacy\|builder_new" -- "*.py"`
Expected: 0 结果

Run: `uv run pytest tests/ -v`
Expected: 全部 PASS

Run: `cd frontend && npx tsc --noEmit`
Expected: 无错误

**Step 6: Commit**

```bash
git add -A
git commit -m "chore: clean version labels, update pyproject.toml and CLAUDE.md"
```

---

### Task 6: 全量验证 + 最终清理

**Step 1: 全量测试**

Run: `uv run pytest tests/ -v --tb=short`
Expected: 全部 PASS，0 failures

**Step 2: TypeScript 检查**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: 无错误

**Step 3: 验证清理目标**

```bash
# cadpilot/ 不存在
ls cadpilot/ 2>&1  # "No such file or directory"

# backend/v1/ 不存在
ls backend/v1/ 2>&1  # "No such file or directory"

# 无 cadpilot import
git grep -r "from cadpilot" -- "*.py"  # 0 结果

# 无双轨构建器
git grep -r "USE_NEW_BUILDER" -- "*.py"  # 0 结果

# 无 builder_legacy 引用
git grep -r "builder_legacy" -- "*.py"  # 0 结果

# 无 builder_new 引用（注释中也清理）
git grep -r "builder_new" -- "*.py"  # 0 结果
```

**Step 4: 如有遗漏，修复并提交**

如果验证发现残留引用，修复后提交：

```bash
git add -A
git commit -m "chore: final cleanup of legacy references"
```
