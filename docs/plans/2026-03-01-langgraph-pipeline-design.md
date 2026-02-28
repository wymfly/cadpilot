# LangGraph CAD 生成管道设计

**日期**: 2026-03-01
**状态**: 待实施
**范围**: 全量迁移 — LangGraph StateGraph 接管 Job 生命周期 + HITL + 事件流

---

## 背景与动机

### 现有问题

| 问题 | 根因 |
|------|------|
| LLM 调用无超时/重试 | 直接调用，hung upstream 导致 SSE 流永久阻塞 |
| `_event_queues` 全局 dict 内存泄漏 | 无界 Queue + 无 TTL，无订阅者时事件累积 |
| HITL 靠 HTTP 状态机拼接 | `confirm` 端点需手动恢复执行上下文，易丢失 |
| 两套"管道"名称（V2/V3）混乱 | 历史遗留命名，不反映实际能力 |

### 目标

1. **LangGraph StateGraph** 统一管理三种输入类型（文本/图纸/创意雕塑）的 Job 生命周期
2. **LCEL with_retry + asyncio.wait_for** 为所有 LLM 调用提供框架级超时/重试/fallback
3. **astream_events** 替换全局 `_event_queues`，事件流生命周期与 Graph Run 绑定，自动清理
4. **AsyncSqliteSaver** 复用现有 `cad3dify.db`，支持断点续跑
5. 废弃 V2/V3 命名，改用**能力描述性命名**（`analyze_vision_spec` / `generate_step_from_template` 等）

---

## 架构设计

### 模块结构

```
backend/
├── graph/                        # 新增：LangGraph 管道
│   ├── __init__.py
│   ├── state.py                  # CadJobState TypedDict
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── analysis.py           # analyze_intent_node, analyze_vision_node
│   │   ├── generation.py         # generate_step_text_node, generate_step_drawing_node
│   │   ├── postprocess.py        # convert_preview_node, check_printability_node
│   │   └── lifecycle.py          # create_job_node, confirm_with_user_node, finalize_node
│   ├── routing.py                # 条件边函数
│   └── builder.py                # compile_graph() → CompiledStateGraph
│
├── pipeline/                     # 保留：底层 CAD 能力（重命名函数，保留逻辑）
│   ├── vision_cad_pipeline.py    # 原 pipeline.py — analyze_vision_spec(), generate_step_from_spec()
│   └── sse_bridge.py             # 废弃（迁移完成后删除）
│
├── api/v1/jobs.py                # 极度精简：路由 → graph.astream_events()
└── api/v1/events.py              # 废弃（_event_queues 删除后删除）
```

### 能力函数重命名对照表

| 旧名称 | 新名称 | 说明 |
|--------|--------|------|
| `analyze_drawing()` | `analyze_vision_spec()` | VL LLM 读图 → DrawingSpec |
| `generate_from_drawing_spec()` | `generate_step_from_spec()` | DrawingSpec → CadQuery → STEP |
| `generate_step_v2()` | `analyze_and_generate_step()` | 组合函数（非 HITL 用） |
| `_run_template_generation()` | `generate_step_from_template()` | 参数化模板渲染 → STEP |
| `_run_analyze_drawing()` | `analyze_vision_spec()` | 同上（wrapper 合并） |
| `_convert_step_to_glb()` | `convert_step_to_preview()` | STEP → GLB |
| `_run_printability_check()` | `check_printability()` | DfAM 可打印性分析 |

---

## StateGraph 设计

### CadJobState

```python
class CadJobState(TypedDict):
    # 输入
    job_id: str
    input_type: str              # "text" | "drawing" | "organic"
    input_text: str | None
    image_path: str | None

    # 分析阶段产物
    intent: dict | None          # IntentSpec.model_dump()
    matched_template: str | None # 模板名称
    drawing_spec: dict | None    # DrawingSpec.model_dump()

    # HITL 确认输入
    confirmed_params: dict | None
    confirmed_spec: dict | None
    disclaimer_accepted: bool

    # 生成产物
    step_path: str | None
    model_url: str | None        # GLB URL
    printability: dict | None

    # 状态与错误
    status: str                  # 对应 JobStatus value
    error: str | None
```

### 节点图

```
[create_job_node]
       │
       ▼ route_by_input_type()
  ┌────┴──────────────┐──────────────┐
  ▼ text              ▼ drawing      ▼ organic
[analyze_intent_node] [analyze_vision_node] [stub_organic_node]
  LCEL chain           asyncio.to_thread      直接发 awaiting
  with_retry(3)        analyze_vision_spec()
  wait_for(60s)
  │                    │              │
  └────────────────────┴──────────────┘
                        ▼
             [confirm_with_user_node]   ← interrupt() 暂停
                        │
                    resume(Command)
                        │
              route_by_input_type_after_confirm()
          ┌───────────────────┐
          ▼ text              ▼ drawing
[generate_step_text_node]  [generate_step_drawing_node]
  TemplateEngine + Sandbox   asyncio.to_thread
  generate_step_from_template generate_step_from_spec()
          │                   │
          └─────────┬─────────┘
                    ▼
         [convert_preview_node]
           convert_step_to_preview()
                    ▼
        [check_printability_node]
           check_printability()
                    ▼
            [finalize_node]
          DB 写 COMPLETED，关闭流
```

### 断点续跑机制

- `interrupt_before=["confirm_with_user_node"]`：图在 HITL 节点前自动 Checkpoint 并暂停
- 每个节点在写 State 前检查幂等条件（如 `step_path` 是否已存在），避免重复执行耗时操作
- `generate_step_drawing_node` 检查：`if state["step_path"] and Path(state["step_path"]).exists(): return state`
- 进程重启后，通过 `thread_id=job_id` 从 AsyncSqliteSaver 恢复，从失败节点重跑

---

## LLM 超时/重试（解决 #3）

```python
# 所有 LLM 节点共用模式
from langchain_core.runnables import RunnableLambda

def build_intent_chain(llm: BaseChatModel) -> Runnable:
    return (
        intent_prompt
        | llm.with_retry(
            stop_after_attempt=3,
            wait_exponential_jitter=True,
        )
        | JsonOutputParser()
    ).with_fallbacks([
        intent_prompt | fallback_llm | JsonOutputParser()
    ])

async def analyze_intent_node(state: CadJobState) -> dict:
    chain = build_intent_chain(primary_llm)
    try:
        result = await asyncio.wait_for(
            chain.ainvoke({"text": state["input_text"]}),
            timeout=60.0,
        )
        await dispatch_custom_event("intent_analyzed", {...})
        return {"intent": result, "status": "intent_parsed"}
    except asyncio.TimeoutError:
        return {"error": "意图解析超时（60s）", "status": "failed"}
    except Exception as exc:
        return {"error": str(exc), "status": "failed"}
```

---

## 事件流（解决 #4）

```python
# builder.py — Graph 编译
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def get_compiled_graph(db_path: str) -> CompiledStateGraph:
    checkpointer = AsyncSqliteSaver.from_conn_string(db_path)
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["confirm_with_user_node"],
    )

# api/v1/jobs.py — POST /api/v1/jobs（精简后）
@router.post("")
async def create_job_endpoint(body: CreateJobRequest) -> EventSourceResponse:
    job_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": job_id}}

    async def event_stream():
        async for event in cad_graph.astream_events(
            {"job_id": job_id, "input_type": body.input_type, ...},
            config=config,
            version="v2",
        ):
            if event["event"] == "on_custom_event":
                yield _sse(event["name"], event["data"])

    return EventSourceResponse(event_stream())

# api/v1/jobs.py — POST /api/v1/jobs/{id}/confirm（精简后）
@router.post("/{job_id}/confirm")
async def confirm_job(job_id: str, body: ConfirmRequest) -> EventSourceResponse:
    config = {"configurable": {"thread_id": job_id}}

    async def event_stream():
        async for event in cad_graph.astream_events(
            Command(resume=body.model_dump()),
            config=config,
            version="v2",
        ):
            if event["event"] == "on_custom_event":
                yield _sse(event["name"], event["data"])

    return EventSourceResponse(event_stream())
```

`_event_queues`、`PipelineBridge`、`emit_event`、`cleanup_queue` **全部删除**。

---

## 规范 SSE 事件命名（建议 #2 同步实施）

| 旧事件名 | 新事件名 | 触发节点 |
|---------|---------|---------|
| `job_created` | `job.created` | `create_job_node` |
| `intent_parsed` | `job.intent_analyzed` | `analyze_intent_node` |
| `analyzing` | `job.vision_analyzing` | `analyze_vision_node` |
| `drawing_spec_ready` | `job.spec_ready` | `analyze_vision_node` |
| `awaiting_confirmation` | `job.awaiting_confirmation` | `confirm_with_user_node` |
| `generating` | `job.generating` | `generate_step_*_node` |
| `refining` | `job.generating` (stage 字段区分) | `generate_step_drawing_node` |
| `completed` | `job.completed` | `finalize_node` |
| `failed` | `job.failed` | 任意节点错误 |
| `heartbeat` | `job.heartbeat` | `events.py` 保留 |

Payload 固定信封：`{job_id, event, stage?, message, data?, ts}`

---

## 依赖变更

```toml
# pyproject.toml 新增
"langgraph>=0.3.0,<1.0",
"langgraph-checkpoint-sqlite>=2.0.0,<3.0",
```

现有 `langchain>=0.3.18` 保留（供 LCEL chain 使用）。
旧式 `LLMChain` / `SequentialChain` 在分析节点中升级为 LCEL（`prompt | llm | parser`）。

---

## 迁移策略

1. **新增 `backend/graph/`**，不改旧代码
2. **能力函数重命名**（`pipeline/vision_cad_pipeline.py`），保留原始实现逻辑
3. **API 层切换**：`jobs.py` 改为调用 `cad_graph.astream_events()`
4. **并行运行期**：旧 `backend/api/generate.py` 端点保留（给 organic 用），待 organic 迁入 Graph 后删除
5. **废弃清理**：`sse_bridge.py`、`events.py`（`_event_queues` 部分）在 Graph 稳定后删除

---

## 验收标准

- [ ] `uv run pytest tests/ -v` 全部通过（1192+）
- [ ] `POST /api/v1/jobs`（text/organic）返回 SSE 流，首个事件为 `job.created`
- [ ] `POST /api/v1/jobs/upload` 返回 SSE 流，含 `job.vision_analyzing` → `job.spec_ready`
- [ ] `POST /api/v1/jobs/{id}/confirm` 恢复 LangGraph 执行，含 `job.generating` → `job.completed`
- [ ] LLM 节点超时 60s 后发 `job.failed` 事件（而非挂起）
- [ ] 进程重启后，通过 `thread_id` 能从 AsyncSqliteSaver 恢复 Job 状态
- [ ] `GET /api/v1/jobs/{id}/events` 端点保持兼容（可选：过渡期保留旧 polling）
- [ ] `_event_queues` 全局 dict 不再存在于代码库
