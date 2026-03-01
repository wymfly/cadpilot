# M3：白盒化 UI — SSE 事件标准化 + 管道 DAG 看板 + Reasoning Trace

> **日期**：2026-03-02
> **来源**：`docs/plans/2026-03-02-gap-implementation-tasks.md` M3
> **模式**：Mode 1 完整路径

---

## 目标

让用户"看透"管道执行过程：实时查看每个节点的状态、耗时、输入/输出和 AI 推理决策链。

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| DAG 定位 | 专家视图并存（保留线性进度条） | 普通用户看进度条，专家切换到 DAG |
| 回溯面板 | DAG 右侧 Drawer | 不占 DAG 空间，Ant Design 原生支持 |
| Reasoning 范围 | 全节点覆盖 | 白盒化彻底 |
| 装饰器范围 | 统一（计时 + SSE + reasoning） | 消除样板代码，事件格式强一致 |
| 架构方案 | 方案 A：装饰器驱动 + 事件归一化 | 一步到位，前端只需订阅两类事件 |

---

## 后端设计

### 1. 统一事件模型

**两层事件**取代当前分散的 `_safe_dispatch` 调用：

| 层 | 事件名 | 发射者 | Payload |
|----|--------|--------|---------|
| 生命周期 | `node.started` | 装饰器 | `{job_id, node, timestamp}` |
| 生命周期 | `node.completed` | 装饰器 | `{job_id, node, elapsed_ms, reasoning, outputs_summary}` |
| 生命周期 | `node.failed` | 装饰器 | `{job_id, node, elapsed_ms, error}` |
| 业务 | `job.awaiting_confirmation` | 节点手动 | HITL 交互点 |
| 业务 | `job.preview_ready` | 节点手动 | `{model_url}` |

现有 `job.generating`、`job.intent_analyzed` 等事件被 `node.completed` 的 `outputs_summary` 替代。

### 2. @timed_node 装饰器

位置：`backend/graph/decorators.py`（新建）

```python
def timed_node(node_name: str):
    """Wrap async graph nodes with lifecycle events + timing + reasoning."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state: CadJobState) -> dict[str, Any]:
            job_id = state["job_id"]
            t0 = time.time()

            await _safe_dispatch("node.started", {
                "job_id": job_id,
                "node": node_name,
                "timestamp": t0,
            })

            try:
                result = await fn(state)
            except Exception as exc:
                elapsed = (time.time() - t0) * 1000
                await _safe_dispatch("node.failed", {
                    "job_id": job_id,
                    "node": node_name,
                    "elapsed_ms": round(elapsed),
                    "error": str(exc),
                })
                raise

            elapsed = (time.time() - t0) * 1000
            reasoning = result.pop("_reasoning", None)

            await _safe_dispatch("node.completed", {
                "job_id": job_id,
                "node": node_name,
                "elapsed_ms": round(elapsed),
                "reasoning": reasoning,
                "outputs_summary": _summarize_outputs(result),
            })

            return result
        return wrapper
    return decorator
```

### 3. Reasoning 传递约定

节点通过返回 dict 的 `_reasoning` 键传递推理数据（下划线前缀 = 元数据，不写入 state）：

```python
@timed_node("analyze_intent")
async def analyze_intent_node(state: CadJobState) -> dict[str, Any]:
    # ... 业务逻辑 ...
    return {
        "intent": intent,
        "matched_template": matched_template,
        "_reasoning": {
            "part_type_detection": "识别为 rotational 基于关键词...",
            "template_selection": f"选择 {matched_template}，覆盖率 0.95",
        },
    }
```

### 4. 各节点 reasoning 内容规划

| 节点 | reasoning 键 | 内容 |
|------|-------------|------|
| create_job | input_type_routing | 路由决策（text/drawing/organic） |
| analyze_intent | part_type_detection, template_selection, recommendations_count | 零件识别、模板匹配、推荐数量 |
| analyze_vision | spec_extraction, confidence | 图纸解析结果、置信度 |
| analyze_organic | shape_classification | 有机形状分类 |
| confirm_with_user | confirmation_type, params_changed | 确认类型、参数变更 |
| generate_step_text | compilation_method, template_or_llm | 模板/LLM 路径选择 |
| generate_step_drawing | pipeline_stages | V2 管道阶段 |
| generate_organic_mesh | mesh_provider, mesh_stats | 网格提供者、统计 |
| convert_preview | format, file_size | 输出格式、文件大小 |
| check_printability | issues_found, printable, material_estimate | 问题数、可打印性、材料估算 |
| finalize | total_duration, final_status | 总耗时、最终状态 |

---

## 前端设计

### 5. 组件架构

```
PipelinePanel (Ant Design Tabs)
  ├── Tab "进度": PipelineProgress (现有，不改)
  ├── Tab "管道": PipelineDAG (新增)
  │     ├── DAGCanvas (ReactFlow 画布)
  │     │   ├── NodeCard (自定义节点)
  │     │   └── AnimatedEdge (自定义边)
  │     └── NodeInspector (Ant Design Drawer)
  │           ├── 输入摘要 (Descriptions)
  │           ├── 输出摘要 (Descriptions)
  │           └── ReasoningCard (Collapse)
  └── Tab "日志": PipelineLog (现有，不改)
```

### 6. DAG 拓扑与路径过滤

静态拓扑定义匹配 `builder.py`，运行时根据 `input_type` 过滤只显示当前路径节点：

- **文本路径**：create_job → analyze_intent → confirm → generate_step_text → convert_preview → check_printability → finalize
- **图纸路径**：create_job → analyze_vision → confirm → generate_step_drawing → convert_preview → check_printability → finalize
- **有机路径**：create_job → analyze_organic → confirm → generate_organic_mesh → postprocess_organic → finalize

### 7. 节点状态机

```
pending (灰色) ──node.started──→ running (蓝色脉冲)
                                   ├──node.completed──→ completed (绿色)
                                   └──node.failed──→ failed (红色)
```

### 8. NodeInspector Drawer

点击已完成/失败节点，右侧滑出 Drawer：

- **标题**：节点中文名 + 状态 + 耗时
- **输入摘要**：该节点接收的关键 state 字段（从 `node.started` 时的 state 快照）
- **输出摘要**：从 `node.completed` 的 `outputs_summary` 读取
- **推理过程**：`ReasoningCard` 组件，从 `node.completed` 的 `reasoning` 读取

### 9. ReasoningCard 组件

```typescript
interface ReasoningCardProps {
  reasoning: Record<string, string> | null;
}
// Ant Design Collapse，每个 key-value 渲染为一个折叠面板
// key 作为面板标题（中文），value 作为面板内容
```

### 10. 前端状态管理

在 `useJobEvents` hook 中新增 `nodeStates` map：

```typescript
interface NodeState {
  status: 'pending' | 'running' | 'completed' | 'failed';
  startedAt?: number;
  elapsedMs?: number;
  reasoning?: Record<string, string>;
  outputsSummary?: Record<string, unknown>;
  error?: string;
}

// useJobEvents 扩展
const [nodeStates, setNodeStates] = useState<Map<string, NodeState>>();
```

---

## 新增依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `@xyflow/react` | ^12 | ReactFlow DAG 可视化 |

---

## 不在范围内

- SSE 事件持久化/回放（M5 数据飞轮范围）
- 节点参数实时编辑/重跑（需要 LangGraph checkpoint 回放）
- 3D 热力图（M4 DfAM 范围）
