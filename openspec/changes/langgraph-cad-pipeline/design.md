## Context

**当前状态**：后端以 `backend/api/v1/jobs.py` 中的手写 async generator 充当编排层，LLM 调用（意图解析、图纸分析）直接 `asyncio.to_thread` 包装同步函数，无超时；SSE 事件通过全局 `_event_queues: dict[str, Queue]` 传递，无生命周期管理；HITL 确认通过 HTTP 状态机（`status=awaiting_confirmation` → POST confirm）拼接，进程重启后上下文丢失。

**约束**：
- 现有 1192 个测试须保持通过
- API 接口签名（endpoint path、request body、SSE 响应格式）保持向后兼容
- 现有 SQLite DB（`backend/data/cad3dify.db`）不迁移，追加 LangGraph checkpoint 表
- V2 管道核心逻辑（DrawingAnalyzer、CodeGenerator、SmartRefiner）保留不重写，以 `asyncio.to_thread` 包装进 Graph 节点

**参考设计文档**：`docs/plans/2026-03-01-langgraph-pipeline-design.md`

---

## Goals / Non-Goals

**Goals:**
- 单一 LangGraph `StateGraph` 统一编排三种 input_type（text / drawing / organic）的 Job 生命周期
- 框架级 LLM 超时/重试：LCEL `.with_retry(3)` + `asyncio.wait_for(60s)` + fallback chain
- 消除 `_event_queues`：改用 `graph.astream_events()` 拉式事件流，生命周期与 Graph Run 绑定
- 原生 HITL：`interrupt_before=["confirm_with_user_node"]` + `Command(resume=...)`；awaiting 事件由前置分析节点在结束前 dispatch（因 `interrupt_before` 会在节点执行前暂停，节点内的 dispatch 不会在首次流中触发）
- 断点续跑：`AsyncSqliteSaver` checkpoint，节点幂等设计，进程重启可从失败节点恢复
- 规范化 SSE 事件命名（`job.created`、`job.generating`、`job.completed` 等）
- 废弃 V2/V3 历史命名，改用能力描述性函数名

**Non-Goals:**
- 不重写 V2 DrawingAnalyzer / CodeGenerator / SmartRefiner 的内部逻辑（仅重命名 + 包装）
- 不迁移 organic 模式实际生成逻辑（仍依赖 `/api/generate/organic` 旧端点，Graph 中仅做 stub）
- 不引入 PostgreSQL 或 Redis（继续用 SQLite）
- 不实现分布式任务队列（Celery / RQ 等）

---

## Decisions

### D1：单一 StateGraph vs 多图（选 B1 单图）

**决定**：使用单一 `CadJobStateGraph`，以条件边区分 text / drawing / organic 路径。

**理由**：
- LangGraph 的 `interrupt()` + `Command(resume=...)` 对所有路径语义一致，单图最简洁
- 共享节点（`convert_preview_node`、`check_printability_node`、`finalize_node`）无需复制
- 单一 `thread_id=job_id` 映射到单一图，状态一致性最强

**替代方案**：三张独立图（text/drawing/organic），优点是每张图更简单，缺点是共享节点重复且 checkpoint 隔离不必要。

---

### D2：Checkpointing 后端（选 AsyncSqliteSaver）

**决定**：使用 `langgraph-checkpoint-sqlite` 的 `AsyncSqliteSaver`，连接现有 `backend/data/cad3dify.db`。

**理由**：
- 零运维成本：复用现有 SQLite 文件，无需部署新基础设施
- LangGraph 的 checkpoint 表（`checkpoints`、`checkpoint_blobs`）自动创建，不影响现有 Job 表
- 开发/生产一致：SQLite 足以支撑单进程部署场景

**替代方案**：`MemorySaver`（进程重启丢失，不支持断点续跑）；PostgreSQL Checkpointer（过重）。

---

### D3：LLM 超时策略（选 LCEL + asyncio.wait_for 双层）

**决定**：每个 LLM 节点用 LCEL `.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)` + 外层 `asyncio.wait_for(timeout=60)` 包裹。文本意图链额外配置 `.with_fallbacks([fallback_chain])`；Vision 链（Qwen-VL-Max）仅 retry 不配 fallback（无等价便宜 VL 模型）。

**理由**：
- LCEL retry 处理临时错误（rate limit、网络抖动）；`wait_for` 处理总预算超限
- `wait_exponential_jitter` 避免同时重试造成 API burst
- 文本意图链 fallback 指向更快/更便宜的模型（如 `gpt-4o-mini`），保障降级可用
- Vision 链无便宜替代品，fallback 无意义，仅依赖 retry + timeout

```python
# 文本意图链（有 fallback）
intent_chain = (prompt | primary_llm.with_retry(stop_after_attempt=3) | parser
                ).with_fallbacks([prompt | fallback_llm | parser])

# Vision 链（仅 retry，无 fallback）
vision_chain = prompt | vl_llm.with_retry(stop_after_attempt=3) | parser

result = await asyncio.wait_for(chain.ainvoke(input), timeout=60.0)
```

---

### D4：事件传递（选 adispatch_custom_event）

**决定**：节点内用 `langchain_core.callbacks.adispatch_custom_event(name, data)` 发送进度事件，API 层通过 `graph.astream_events(..., version="v2")` 过滤 `on_custom_event` 类型。

**理由**：
- 框架原生机制，生命周期由 Graph Run 管理，Graph 结束时自动清理，无需手动 `cleanup_queue()`
- 不同节点的事件自动携带 `run_id`、`tags`，可按节点过滤

**替代方案**：保留 `_event_queues`（需手动 TTL 清理，内存泄漏风险）；Redis Pub/Sub（引入新依赖）。

---

### D5：节点幂等设计（断点续跑关键）

**决定**：耗时节点在执行前检查输出是否已存在，存在则跳过。

```python
async def generate_step_drawing_node(state: CadJobState) -> dict:
    if state.get("step_path") and Path(state["step_path"]).exists():
        return {}  # 已生成，跳过
    ...
```

**理由**：AsyncSqliteSaver 保存节点完成后的 State，重启后从 checkpoint 恢复到失败节点重跑；幂等设计保证重跑安全。

---

### D6：能力函数重命名（vs 保持旧名）

**决定**：在 `backend/pipeline/vision_cad_pipeline.py`（原 `pipeline.py`）中重命名导出函数。

| 旧名 | 新名 |
|------|------|
| `analyze_drawing()` | `analyze_vision_spec()` |
| `generate_from_drawing_spec()` | `generate_step_from_spec()` |
| `generate_step_v2()` | `analyze_and_generate_step()` |

**理由**：消除 V2/V3 历史标签，名称直接描述能力。旧名保留 alias 一个版本后删除。

---

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| LangGraph API 变更（当前 1.0.x 已发布） | 锁定 `>=0.3.0`（兼容 1.0.x），集成测试覆盖 Graph 核心路径；实施前运行 API 兼容性烟雾测试 |
| AsyncSqliteSaver 与 aiohttp 的并发写冲突 | SQLite WAL 模式（LangGraph 默认启用），单进程部署无并发写问题 |
| 断点续跑时 V2 管道部分输出（非原子） | `generate_step_drawing_node` 先写临时文件再 rename，确保原子性 |
| 测试中 LangGraph + FastAPI TestClient 的事件流兼容性 | 使用 `graph.invoke()` 模式在单元测试中替代 `astream_events()` |
| SSE 事件名称变更导致前端不兼容 | 前端适配新事件名（`job.created` 等），过渡期可在 API 层同时发旧名事件 |

---

## Migration Plan

1. **安装依赖**：`uv add langgraph langgraph-checkpoint-sqlite`
2. **新建 `backend/graph/`**：state.py → nodes/ → routing.py → builder.py，不动旧代码
3. **重命名能力函数**：`pipeline/vision_cad_pipeline.py`，旧名保留 alias
4. **API 层切换**：`jobs.py` 逐端点替换为 `graph.astream_events()`
5. **删除废弃代码**：`_event_queues`、`PipelineBridge`、旧 SSE generator（所有测试通过后）
6. **更新测试**：适配新事件名称，新增 Graph 节点单元测试

**字段映射**：`CadJobState` 字段名与 ORM `Job` 模型需显式映射——`confirmed_spec` ↔ `drawing_spec_confirmed`，`printability` ↔ `printability_result`，`step_path` ↔ `output_step_path`。`finalize_node` 负责将 State 字段写入 ORM 时做转换。

**回滚**：`backend/graph/` 是新增模块，旧代码在独立 git 分支保留；若 Graph 路径失败，API 层可快速切回旧 generator。

---

## Open Questions

- **organic 节点**：目前 Graph 中 organic 路径做 stub（直接进 `confirm_with_user_node`），确认后 `finalize_node` 将 Job 标记为外部处理，实际生成仍由 `/api/generate/organic` 旧端点完成。organic 节点不路由到 drawing/text 生成路径。何时将 organic 生成逻辑迁入 Graph？（建议单独 change 处理）
- **`backend/api/generate.py` 遗留依赖**：`generate.py` 仍使用 `PipelineBridge` 和 `_event_queues`；因 organic 仍依赖此端点，本次变更不删除 `sse_bridge.py` 和 `events.py` 中被 `generate.py` 引用的部分。仅删除被 `jobs.py` 独占的废弃代码
- **并发 Job**：同一用户多个并发 Job 是否需要 Graph 层面的资源限制？（当前单进程 SQLite 可接受）
- **事件过渡期**：是否需要同时发新旧格式事件以支持前端灰度？（建议直接切换，前端同步改）
