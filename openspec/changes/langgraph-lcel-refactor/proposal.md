## Why

项目核心 LLM 调用仍使用 LangChain 的 `SequentialChain`（已标记为 Legacy），且编排逻辑隐藏在 `backend/pipeline/pipeline.py` 中以同步方式执行，与外层 LangGraph 异步节点之间通过 `asyncio.to_thread()` 桥接。这导致三个问题：（1）LLM 调用的可观测性差——提示词、模型选择、重试逻辑分散在 core/ 模块深处，节点层面无法追踪；（2）同步/异步模式混杂——SequentialChain.invoke() 是同步的，必须用 to_thread 包装后才能在 async 节点中运行；（3）pipeline.py 的 Best-of-N 多路生成和 SmartRefiner ≤3 轮循环逻辑无法利用 LangGraph 的状态管理和检查点恢复能力。

## What Changes

- **BREAKING**: 删除 `DrawingAnalyzerChain`、`CodeGeneratorChain`、`SmartCompareChain`、`SmartFixChain` 四个 SequentialChain 类，替换为 LCEL Runnable（`prompt | llm | parser`）
- **BREAKING**: 删除 `backend/pipeline/pipeline.py` 中的 `analyze_vision_spec()`、`generate_step_from_spec()` 编排函数，将其逻辑直接内联到对应 LangGraph 节点中
- 统一所有 LLM 调用为原生异步（`ainvoke()`），消除 `asyncio.to_thread()` 包装
- SmartRefiner 的 Compare→Fix 循环改为 LangGraph 子图（subgraph），支持检查点恢复
- Best-of-N 代码生成改为节点内异步并发（`asyncio.gather`），不再串行
- 保留 `get_model_for_role()` 模型选择机制和 `ModelingStrategist` 纯规则引擎（无 LLM，不动）
- 保留 `IntentParser` 和 `OrganicSpecBuilder` 现有异步模式（已接近原生，仅做轻微统一）

## Capabilities

### New Capabilities
- `lcel-chain-builders`: LCEL Runnable 构建器模块——为项目中所有 LLM 调用场景（视觉分析、代码生成、VL 对比、代码修复）提供统一的 `async def build_xxx_chain() -> Runnable` 工厂函数
- `refiner-subgraph`: SmartRefiner 子图——将 Compare→Fix ≤3 轮循环建模为 LangGraph 子图，支持检查点和 SSE 进度事件

### Modified Capabilities
- `langgraph-job-orchestration`: 分析节点和生成节点不再委托给 pipeline.py 编排函数，而是直接使用 LCEL chain 和内联编排逻辑
- `llm-resilience`: retry/fallback 现在包装 LCEL Runnable 而非 SequentialChain

## Impact

- **删除文件**: `backend/pipeline/pipeline.py` 中的 `analyze_vision_spec()`、`generate_step_from_spec()` 函数（保留文件，其他工具函数仍需要）
- **重写文件**: `backend/core/drawing_analyzer.py`、`backend/core/code_generator.py`、`backend/core/smart_refiner.py`
- **新建文件**: `backend/graph/chains/` 目录（LCEL 构建器）、`backend/graph/subgraphs/refiner.py`（Refiner 子图）
- **修改节点**: `backend/graph/nodes/analysis.py`（analyze_vision）、`backend/graph/nodes/generation.py`（generate_step_drawing、generate_step_text）
- **测试影响**: 所有 chain 相关测试需重写 mock 模式，从 mock `SequentialChain.invoke()` 改为 mock LCEL `ainvoke()`
- **依赖**: 不新增外部依赖（LCEL 是 langchain_core 内置功能）
