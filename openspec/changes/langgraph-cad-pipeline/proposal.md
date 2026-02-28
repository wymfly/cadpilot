## Why

当前 CAD 生成管道存在三个关键缺陷：LLM 调用无超时导致 SSE 流永久挂起、全局 `_event_queues` 字典无生命周期管理造成内存泄漏、HITL 确认通过 HTTP 状态机拼接导致上下文丢失且无法断点续跑。引入 LangGraph 统一编排是一次性解决这三个问题的最直接路径，同时消除 V2/V3 历史命名混乱。

## What Changes

- **新增** `backend/graph/` 模块：LangGraph `StateGraph` 接管全部 Job 生命周期（创建 → 分析 → HITL → 生成 → 后处理 → 完成）
- **新增** LangGraph `interrupt()` / `Command(resume=...)` 原生 HITL 机制，替换现有 HTTP 状态机
- **新增** `AsyncSqliteSaver` checkpointing，复用现有 `cad3dify.db`，支持断点续跑
- **新增** LCEL `.with_retry()` + `asyncio.wait_for()` 为所有 LLM 节点提供框架级超时/重试/fallback
- **修改** `backend/api/v1/jobs.py`：POST 端点改为调用 `graph.astream_events()`，删除手写 SSE 生成器
- **修改** `backend/pipeline/pipeline.py`：函数重命名为能力描述性名称（`analyze_vision_spec`、`generate_step_from_spec` 等），逻辑不变
- **清理** `backend/api/v1/jobs.py` 中对 `_event_queues`、`emit_event`、`PipelineBridge` 的所有引用（`events.py` 和 `sse_bridge.py` 文件本身保留，因 `backend/api/generate.py` organic 旧端点仍依赖）
- **规范化** SSE 事件命名为 `job.<stage>` 格式（`job.created`、`job.generating`、`job.completed` 等）
- **BREAKING** SSE 事件名称从 `job_created`/`intent_parsed` 等升级为 `job.created`/`job.intent_analyzed` 等；API 端点签名和 SSE 流式响应格式本身不变

## Capabilities

### New Capabilities

- `langgraph-job-orchestration`：LangGraph StateGraph 管理 CAD Job 完整生命周期，包含条件路由、节点级错误处理、AsyncSqliteSaver checkpointing 和断点续跑
- `llm-resilience`：LCEL with_retry + asyncio.wait_for 为所有 LLM 节点提供超时（60s）、重试（3次）保障；文本意图链额外配置 fallback 模型（vision 链无 fallback——VL 模型无便宜替代）
- `graph-event-streaming`：通过 `adispatch_custom_event` + `graph.astream_events()` 实现拉式事件流，替代推式全局 Queue，生命周期与 Graph Run 绑定

### Modified Capabilities

- `hitl-confirmation`：HITL 从"HTTP POST 恢复状态"改为 LangGraph `interrupt()` / `Command(resume=...)` 模式，语义更强，支持 checkpoint 恢复

## Impact

- **新依赖**：`langgraph>=0.3.0`、`langgraph-checkpoint-sqlite>=2.0.0`
- **API 兼容**：`POST /api/v1/jobs`、`POST /api/v1/jobs/upload`、`POST /api/v1/jobs/{id}/confirm` 接口签名不变，响应格式（SSE 流）不变；**事件名称 BREAKING 变更**——从 `job_created`/`intent_parsed` 升级为 `job.created`/`job.intent_analyzed`（需前端同步适配）
- **DB**：现有 `cad3dify.db` 增加 LangGraph checkpoint 表（`checkpoints`、`checkpoint_blobs`），不影响现有 Job 表
- **测试**：现有 1192 个测试需适配新事件名称；新增 Graph 节点单元测试和 HITL 集成测试
