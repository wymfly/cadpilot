## 1. 依赖安装与项目配置

- [ ] 1.1 在 `pyproject.toml` 添加 `langgraph>=0.3.0` 和 `langgraph-checkpoint-sqlite>=2.0.0`
- [ ] 1.2 运行 `uv add langgraph langgraph-checkpoint-sqlite` 并提交 `uv.lock`
- [ ] 1.3 验证 `uv run python -c "import langgraph; from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver; from langchain_core.callbacks import adispatch_custom_event"` 无错误
- [ ] 1.4 运行 LangGraph API 兼容性烟雾测试：验证 `StateGraph`、`interrupt_before`、`Command`、`astream_events(version="v2")` 在当前安装版本中均可用

## 2. CadJobState 与 Graph 状态定义

- [ ] 2.1 创建 `backend/graph/__init__.py`（空文件）
- [ ] 2.2 创建 `backend/graph/state.py`：定义 `CadJobState` TypedDict（字段：job_id, input_type, input_text, image_path, intent, matched_template, drawing_spec, confirmed_params, confirmed_spec, disclaimer_accepted, step_path, model_url, printability, status, error, failure_reason）
- [ ] 2.3 在 `state.py` 中定义 `STATE_TO_ORM_MAPPING` 字典，映射 CadJobState 字段 → ORM Job 字段（`confirmed_spec` → `drawing_spec_confirmed`，`printability` → `printability_result`，`step_path` → `output_step_path`）

## 3. 能力函数重命名（pipeline 层）

- [ ] 3.1 将 `backend/pipeline/pipeline.py` 重命名为 `backend/pipeline/vision_cad_pipeline.py`
- [ ] 3.2 在 `vision_cad_pipeline.py` 中将 `analyze_drawing()` 重命名为 `analyze_vision_spec()`，保留旧名 alias 一个版本
- [ ] 3.3 将 `generate_from_drawing_spec()` 重命名为 `generate_step_from_spec()`，保留旧名 alias
- [ ] 3.4 将 `generate_step_v2()` 重命名为 `analyze_and_generate_step()`，保留旧名 alias
- [ ] 3.5 将 `_convert_step_to_glb()` 重命名为 `convert_step_to_preview()`，保留旧名 alias
- [ ] 3.6 将 `_run_printability_check()` 重命名为 `check_printability()`，保留旧名 alias
- [ ] 3.7 更新所有 import 引用新函数名（搜索全项目，含 `backend/api/generate.py`）
- [ ] 3.8 运行 `uv run pytest tests/ -v` 确认现有 1192 个测试仍通过

## 4. Graph 节点实现

- [ ] 4.1 创建 `backend/graph/nodes/__init__.py`
- [ ] 4.2 创建 `backend/graph/nodes/lifecycle.py`：实现 `create_job_node`（创建 DB Job，使用 `langchain_core.callbacks.adispatch_custom_event` dispatch `job.created` 事件）
- [ ] 4.3 在 `lifecycle.py` 实现 `confirm_with_user_node`（处理 `Command(resume=...)` 返回的确认数据，将 confirmed_spec/confirmed_params 写入 State；注意此节点在首次流中不执行——`interrupt_before` 在此节点前暂停）
- [ ] 4.4 在 `lifecycle.py` 实现 `finalize_node`（使用 `STATE_TO_ORM_MAPPING` 将 CadJobState 字段映射到 ORM 字段，更新 DB 为 COMPLETED/FAILED，dispatch `job.completed` 或 `job.failed`）
- [ ] 4.5 创建 `backend/graph/nodes/analysis.py`：实现 `analyze_intent_node`（LCEL chain with_retry + with_fallbacks + asyncio.wait_for 60s，dispatch `job.intent_analyzed` 和 `job.awaiting_confirmation`——awaiting 事件在此节点结束时 dispatch，因 interrupt_before 在 confirm 节点前暂停）
- [ ] 4.6 在 `analysis.py` 实现 `analyze_vision_node`（asyncio.to_thread 包装 `analyze_vision_spec()`，dispatch `job.vision_analyzing`、`job.spec_ready` 和 `job.awaiting_confirmation`——awaiting 事件在此节点结束时 dispatch）
- [ ] 4.7 在 `analysis.py` 实现 `stub_organic_node`（dispatch `job.awaiting_confirmation`，不做 LLM 分析）
- [ ] 4.8 创建 `backend/graph/nodes/generation.py`：实现 `generate_step_text_node`（TemplateEngine + Sandbox，dispatch `job.generating`，幂等检查）
- [ ] 4.9 在 `generation.py` 实现 `generate_step_drawing_node`（asyncio.to_thread 包装 `generate_step_from_spec()`，dispatch `job.generating`，幂等检查：`if state["step_path"] and Path(state["step_path"]).exists(): return {}`）
- [ ] 4.10 创建 `backend/graph/nodes/postprocess.py`：实现 `convert_preview_node`（asyncio.to_thread 包装 `convert_step_to_preview()`，dispatch `job.preview_ready`）
- [ ] 4.11 在 `postprocess.py` 实现 `check_printability_node`（asyncio.to_thread 包装 `check_printability()`，dispatch `job.printability_ready`）

## 5. Graph 路由与构建

- [ ] 5.1 创建 `backend/graph/routing.py`：实现 `route_by_input_type(state)` 返回 `"text"` | `"drawing"` | `"organic"`
- [ ] 5.2 在 `routing.py` 实现 `route_after_confirm(state)` 返回 `"text"` | `"drawing"` | `"organic_external"`（organic 确认后标记为外部处理，由 finalize_node 写入 DB 后退出 Graph，实际生成仍由 `/api/generate/organic` 旧端点完成）
- [ ] 5.3 创建 `backend/graph/builder.py`：定义 `CadJobStateGraph` StateGraph，添加所有节点，添加条件边（route_by_input_type → analysis nodes）
- [ ] 5.4 在 `builder.py` 实现 `get_compiled_graph(db_path: str) -> CompiledStateGraph`：使用 `AsyncSqliteSaver.from_conn_string(db_path)` 作为 checkpointer，`interrupt_before=["confirm_with_user_node"]`
- [ ] 5.5 在 `backend/graph/__init__.py` 导出 `get_compiled_graph`

## 6. LLM 超时/重试工具

- [ ] 6.1 创建 `backend/graph/llm_utils.py`：实现 `build_intent_chain(primary_llm, fallback_llm) -> Runnable`（LCEL with_retry + with_fallbacks）
- [ ] 6.2 在 `llm_utils.py` 实现 `build_vision_chain(primary_llm) -> Runnable`（with_retry 但无 fallback——VL 模型无便宜替代）
- [ ] 6.3 在 `llm_utils.py` 实现 `map_exception_to_failure_reason(exc) -> str`：将异常映射为 typed failure_reason（`timeout` | `rate_limited` | `invalid_json` | `generation_error`）
- [ ] 6.4 为 chain 和 failure mapping 添加单元测试（mock LLM，验证 retry 次数、fallback 触发、failure_reason 分类）

## 7. API 层切换

- [ ] 7.1 在 `backend/main.py`（或 lifespan）初始化 `cad_graph = await get_compiled_graph(DB_PATH)`，作为应用级单例
- [ ] 7.2 修改 `backend/api/v1/jobs.py` 中的 POST `/api/v1/jobs` 端点：替换手写 SSE 生成器为 `cad_graph.astream_events(initial_state, config, version="v2")` + `on_custom_event` 过滤
- [ ] 7.3 修改 POST `/api/v1/jobs/upload` 端点：同样替换为 Graph astream_events
- [ ] 7.4 修改 POST `/api/v1/jobs/{id}/confirm` 端点：替换为 `cad_graph.astream_events(Command(resume=body.model_dump()), config, version="v2")`；在 confirm 节点恢复后执行 corrections 双写（JSON + DB，WARNING 级别日志记录失败）
- [ ] 7.5 保留 GET `/api/v1/jobs/{id}/events` 端点（heartbeat 轮询，过渡期不删除）

## 8. 废弃代码清理

- [ ] 8.1 从 `backend/api/v1/jobs.py` 中移除对 `_event_queues`、`emit_event`、`cleanup_queue`、`PipelineBridge` 的所有引用
- [ ] 8.2 从 `backend/api/v1/jobs.py` 中删除已废弃的手写 SSE 生成器函数（`_text_sse_generator` 等）
- [ ] 8.3 **不删除** `backend/pipeline/sse_bridge.py` 和 `backend/api/v1/events.py` 中被 `backend/api/generate.py` 依赖的部分（organic 仍使用旧端点，待 organic 迁移 change 处理）
- [ ] 8.4 验证 `backend/api/generate.py` 仍可正常编译运行（不因 jobs.py 清理而崩溃）

## 9. 测试更新与新增

- [ ] 9.1 更新现有测试中使用旧 SSE 事件名（`job_created`、`intent_parsed` 等）的断言，改为新名（`job.created`、`job.intent_analyzed` 等）
- [ ] 9.2 新增 `tests/test_graph_nodes.py`：为每个 Graph 节点编写单元测试（mock 外部依赖，验证 State 更新和 dispatch 事件）
- [ ] 9.3 新增 `tests/test_graph_builder.py`：编译 Graph，用 `graph.invoke()` 模式（非 astream_events）测试完整 text 路径和 drawing 路径
- [ ] 9.4 新增 HITL 集成测试：验证 `interrupt_before` 暂停后 `Command(resume=...)` 能正确恢复执行，且 awaiting 事件在 interrupt 前已被 dispatch
- [ ] 9.5 新增 LLM 超时测试：mock chain 模拟 asyncio.TimeoutError，验证节点返回 `{"status": "failed", "failure_reason": "timeout"}` 而非挂起
- [ ] 9.6 新增 corrections 双写测试：验证 confirm 后 JSON 和 DB 均写入 corrections，失败时 WARNING 日志
- [ ] 9.7 新增 State→ORM 映射测试：验证 `finalize_node` 使用 `STATE_TO_ORM_MAPPING` 正确写入 DB 字段
- [ ] 9.8 运行 `uv run pytest tests/ -v` 确认全部测试通过（≥1192 个）

## 10. 验收检查

- [ ] 10.1 验证 `uv run pytest tests/ -v` 全部通过
- [ ] 10.2 手动测试 POST /api/v1/jobs（text）：首个 SSE 事件为 `job.created`
- [ ] 10.3 手动测试 POST /api/v1/jobs/upload（drawing）：含 `job.vision_analyzing` → `job.spec_ready` → `job.awaiting_confirmation`
- [ ] 10.4 手动测试 POST /api/v1/jobs/{id}/confirm：返回 `job.generating` → `job.completed`
- [ ] 10.5 验证 LLM 节点超时 60s 后发 `job.failed` 而非挂起，payload 含 `failure_reason`
- [ ] 10.6 验证进程重启后通过 `thread_id` 能从 AsyncSqliteSaver 恢复 Job 状态
- [ ] 10.7 确认 `jobs.py` 中不再引用 `_event_queues`（`grep -r "_event_queues" backend/api/v1/jobs.py` 无输出）
- [ ] 10.8 确认 `backend/api/generate.py`（organic 旧端点）仍可正常运行
