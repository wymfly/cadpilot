## Context

CADPilot 使用 LangGraph 作为 Job 编排框架（`@register_node` + `CadJobState` + `StateGraph`），但核心 LLM 调用仍依赖 LangChain 的 `SequentialChain`（`LLMChain + TransformChain` 组合）。这些 Chain 隐藏在 `backend/core/` 模块中，被 `backend/pipeline/pipeline.py` 的同步函数编排，再由 LangGraph 节点通过 `asyncio.to_thread()` 调用。

当前 LLM 调用栈（以图纸路径为例）：
```
analyze_vision_node (async)
  → asyncio.to_thread(_run_analyze_vision)
    → pipeline.analyze_vision_spec() (sync)
      → DrawingAnalyzerChain().invoke() (sync SequentialChain)
        → LLMChain → VL model → TransformChain → DrawingSpec

generate_step_drawing_node (async)
  → asyncio.to_thread(_run_generate_from_spec)
    → pipeline.generate_step_from_spec() (sync, ~400 行)
      → ModelingStrategist.select() (纯规则，无 LLM)
      → CodeGeneratorChain().invoke() (sync, 可能 N 次 Best-of-N)
      → SmartRefiner.refine() (sync, ≤3 轮循环)
        → SmartCompareChain().invoke() (sync VL)
        → SmartFixChain().invoke() (sync Coder)
```

四层间接调用（async 节点 → to_thread → pipeline 函数 → SequentialChain）导致可观测性差、错误追踪困难、检查点无法在 LLM 调用粒度恢复。

## Goals / Non-Goals

**Goals:**
- 将 4 个 SequentialChain 替换为 LCEL Runnable（`prompt | llm | parser`），全部异步 `ainvoke()`
- 将 `pipeline.py` 的 `analyze_vision_spec()` 和 `generate_step_from_spec()` 编排逻辑内联到 LangGraph 节点中，消除 `asyncio.to_thread()` 中间层
- SmartRefiner 的 Compare→Fix 循环建模为 LangGraph 子图，支持按轮检查点恢复和 SSE 进度事件
- Best-of-N 代码生成改为异步并发（`asyncio.gather`）
- 保持所有 LLM 调用的提示词不变（仅改调用方式，不改提示内容）

**Non-Goals:**
- 不修改 `IntentParser` 和 `OrganicSpecBuilder`（已接近原生 async 模式）
- 不修改 `ModelingStrategist`（纯规则引擎，无 LLM 调用）
- 不修改 LangGraph 节点的注册机制（`@register_node`）和状态 schema（`CadJobState`）
- 不修改 `get_model_for_role()` 模型选择机制和 `llm_config.yaml` 配置
- 不修改 `SafeExecutor`（CadQuery 沙箱执行）和几何校验逻辑
- 不引入 LangGraph Agent / Tool calling（保持确定性管道）
- 不删除 `pipeline.py` 文件本身（保留工具函数如 `_score_geometry`、`analyze_and_generate_step`）

## Decisions

### ADR-1: LCEL Runnable 构建器放在 `backend/graph/chains/` 而非 `backend/core/`

**决策：** 在 `backend/graph/chains/` 创建独立模块，每个 Chain 对应一个 `build_xxx_chain() -> Runnable` 工厂函数。

**理由：**
- `backend/core/` 中的旧 Chain 类与 core 域逻辑（DrawingSpec、ModelingContext 等数据模型）耦合。将新的 LCEL Runnable 放在 `backend/graph/` 下，明确"LLM 调用是图编排层的职责"
- 工厂函数模式便于测试——可以 mock `get_model_for_role()` 返回值后验证 chain 结构
- 旧 `backend/core/` 文件中的辅助函数（`_parse_drawing_spec`、`_parse_code`、`_extract_comparison`、`fuse_ocr_with_spec`）保留原位，由 chain builder import 调用

**替代方案：**
- 原地重写 `backend/core/` 文件 → 拒绝：破坏 core 层只包含业务逻辑和数据模型的边界
- 放在 `backend/graph/nodes/` 同文件 → 拒绝：节点文件已较长，chain 构建逻辑会使其膨胀

**文件结构：**
```
backend/graph/chains/
├── __init__.py           # re-export build_* functions
├── vision_chain.py       # build_vision_analysis_chain()
├── code_gen_chain.py     # build_code_gen_chain()
├── compare_chain.py      # build_compare_chain(structured=False)
└── fix_chain.py          # build_fix_chain()
```

### ADR-2: SmartRefiner 循环改为 LangGraph 子图而非节点内 while 循环

**决策：** 将 Compare→Fix→Re-execute→Re-render ≤3 轮循环建模为 `StateGraph` 子图（subgraph），嵌入 `generate_step_drawing_node` 后的图拓扑中。

**理由：**
- 子图中每个节点（compare、fix、re-execute）都是检查点边界，进程崩溃后可从最近一轮恢复
- 每轮循环可以独立派发 SSE 事件（`job.refining`），前端实时显示第几轮
- 循环退出条件（VL PASS 或达到上限）通过 conditional edge 路由，比 while 循环更可视化

**替代方案：**
- 节点内 while 循环 + 手动状态管理 → 拒绝：无检查点粒度，崩溃后从头重跑 3 轮
- 每轮循环作为顶层独立节点 → 拒绝：污染主图拓扑，且轮数不固定

**子图状态：**
```python
class RefinerState(TypedDict):
    code: str                  # 当前 CadQuery 代码
    step_path: str             # STEP 文件路径
    drawing_spec: dict         # 图纸规格
    image_path: str            # 原始图纸路径
    round: int                 # 当前轮次
    max_rounds: int            # 最大轮次
    verdict: str               # "pending" | "pass" | "fail"
    static_notes: list[str]    # Layer 1/2 诊断
```

### ADR-3: pipeline.py 编排函数渐进式迁移而非一次性删除

**决策：** 分两步迁移：
1. 先创建 LCEL chains + refiner 子图，节点层直接使用新 chain
2. 再删除 `pipeline.py` 中的 `analyze_vision_spec()` 和 `generate_step_from_spec()`

保留 `pipeline.py` 中的工具函数（`_score_geometry`、`analyze_and_generate_step`），因为 `analyze_and_generate_step` 被非 LangGraph 入口（CLI、测试）调用。

**理由：**
- 一次性删除风险高——pipeline.py 是 486 行的密集编排逻辑
- 渐进式迁移允许逐个验证每条 chain 的行为等价性
- `analyze_and_generate_step()` 入口函数可在未来改为调用 LangGraph 图代替，但不在本次范围

### ADR-4: Best-of-N 改为 asyncio.gather 并发而非串行

**决策：** 将 Best-of-N 循环从 `for i in range(N): generator.invoke(ctx)` 改为 `asyncio.gather(*[chain.ainvoke(ctx) for _ in range(N)])`。

**理由：**
- N 个候选完全独立，并发执行可将延迟从 N×T 降至 ~T
- 每个候选仍需串行 execute + score（CadQuery 执行依赖文件系统），用 tempdir 隔离
- LCEL Runnable 原生支持 `ainvoke`，并发无额外成本

**替代方案：**
- 保持串行 → 拒绝：N=3 时延迟从 ~90s 降至 ~30s，收益明显
- 用 LangGraph Parallel Node → 拒绝：Best-of-N 是生成节点的内部策略，不值得暴露为图拓扑

### ADR-5: 旧 Chain 类标记为 @deprecated 保留一个版本周期后删除

**决策：** 第一步迁移完成后，旧 `DrawingAnalyzerChain`、`CodeGeneratorChain`、`SmartCompareChain`、`SmartFixChain` 标记 `@deprecated`，`analyze_and_generate_step()` 函数内部保留对旧 Chain 的调用。下一个版本周期再统一删除。

**理由：**
- `analyze_and_generate_step()` 是非 LangGraph 入口（CLI、benchmark 测试可能使用）
- 一步删除要求同时修改所有消费方，风险较高
- 标记 deprecated 后可通过 `grep` 追踪剩余使用方

## Risks / Trade-offs

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| **提示词行为不一致** — LCEL 管道与 SequentialChain 的提示词格式化可能有微妙差异 | 中 | 高 | 每个 chain 迁移后运行 prompt 等价性测试（相同输入→相同 prompt text） |
| **子图状态映射错误** — Refiner 子图与主图的状态字段映射不正确 | 中 | 高 | 子图使用独立 TypedDict，通过显式映射函数在进出子图时转换 |
| **并发 Best-of-N 资源竞争** — 多个 CadQuery 执行同时写文件 | 低 | 中 | 每个候选使用独立 tempdir 隔离 |
| **测试回归** — 大量测试 mock 需要从 `.invoke()` 改为 `.ainvoke()` | 高 | 中 | 先创建测试工具函数（mock LCEL chain factory），再批量迁移 |
| **pipeline.py 残留调用** — 迁移不彻底导致新旧混用 | 低 | 低 | 迁移完成后 grep 验证无 `pipeline.analyze_vision_spec` / `pipeline.generate_step_from_spec` 调用 |
