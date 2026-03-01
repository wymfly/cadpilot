# Organic 管道 LangGraph 迁移设计

**日期**: 2026-03-01
**状态**: 已确认
**范围**: 将创意雕塑（organic）管道从独立 FastAPI 编排迁入 LangGraph StateGraph，统一三种 input_type 的生命周期管理

---

## 背景

精密建模管道（text/drawing）已使用 LangGraph StateGraph 管理 Job 生命周期，包括 HITL 中断/恢复、统一 SSE 事件流。但创意雕塑（organic）管道仍使用独立的 FastAPI 异步生成器手工编排，存在以下问题：

| 问题 | 根因 |
|------|------|
| 两套 API 端点并存 | `/api/v1/jobs` vs `/api/v1/organic`，前端需维护两套调用逻辑 |
| 两套数据模型 | `JobModel` vs `OrganicJobModel`，数据分散在两张表 |
| 无 HITL 确认 | organic 管道直接执行，用户无法在生成前确认/调整 spec |
| SSE 事件格式不统一 | organic 用 `event: "organic"`，精密用 `job.*` 命名空间 |
| 无框架级超时/重试 | organic 的 LLM 调用和 Provider 调用无统一保护 |

---

## 方案选择

**方案 A（采纳）：图内编排** — organic 作为 CadJobState 图的第三条路径，与 text/drawing 共用节点（create_job、confirm_with_user、finalize），新增 3 个 organic 专有节点。

**方案 B（否决）：子图封装** — organic 封装为独立 SubGraph。否决原因：astream_events 嵌套复杂、HITL 中断跨子图传播困难、增加不必要的状态映射层。

---

## 设计详情

### 1. CadJobState 扩展

```python
class CadJobState(TypedDict, total=False):
    # ... 现有字段不变 ...

    # ── Organic 专有 ──
    organic_spec: dict | None            # OrganicSpec.model_dump()
    organic_provider: str | None         # "auto" | "tripo3d" | "hunyuan3d"
    organic_quality_mode: str | None     # "draft" | "standard" | "high"
    organic_reference_image: str | None  # 上传的 file_id
    raw_mesh_path: str | None            # Provider 生成的原始网格路径
    mesh_stats: dict | None              # MeshStats.model_dump()
    organic_warnings: list[str]          # 后处理警告
    organic_result: dict | None          # {model_url, stl_url, threemf_url, ...}
```

### 2. 图拓扑

```
[create_job_node]
       │
       ▼ route_by_input_type()
  ┌────┴──────────────┐──────────────┐
  ▼ text              ▼ drawing      ▼ organic
[analyze_intent]  [analyze_vision]  [analyze_organic]  ← 替换 stub
  │                    │              │
  └────────────────────┴──────────────┘
                       ▼
            [confirm_with_user]   ← interrupt（三种类型共用）
                       │
             route_after_confirm()
         ┌──────────┬──────────────┐
         ▼ text     ▼ drawing     ▼ organic
  [generate_text] [generate_drawing] [generate_organic_mesh]  ← 新增
         │              │              │
         ▼              ▼              │
  [convert_preview]     │              │
         │              │              │
         ▼              ▼              ▼
  [check_printability]  │     [postprocess_organic]  ← 新增
         │              │              │
         └──────────────┴──────────────┘
                        ▼
                   [finalize]
```

- `stub_organic_node` → `analyze_organic_node`（调用 OrganicSpecBuilder）
- `route_after_confirm` 新增 `"organic"` → `"generate_organic_mesh"` 路由
- organic 路径不经过 `convert_preview`（无 STEP 文件）
- `postprocess_organic_node` 内含导出和可打印性检查，完成后直接到 `finalize`

### 3. 新增节点

#### analyze_organic_node

替换 `stub_organic_node`。调用 `OrganicSpecBuilder.build()` 进行 prompt 翻译和 spec 构建。

- 超时 60s（与 intent/vision 一致）
- 成功后 dispatch `job.organic_spec_ready` 事件，payload 含完整 spec
- 设置 status = `awaiting_confirmation`，触发 HITL 中断

#### generate_organic_mesh_node

调用 MeshProvider（Tripo3D / Hunyuan3D / Auto）生成原始网格。

- 幂等检查：`if state.get("raw_mesh_path") and Path(...).exists(): return {}`
- 读取 reference_image（如有 file_id）
- dispatch `job.generating` 事件，stage = `"mesh_generation"`
- Provider 内部有轮询超时（Tripo3D 5min），不额外加 asyncio.wait_for

#### postprocess_organic_node

在一个节点内顺序执行 5 个子步骤 + 导出 + 可打印性检查：

1. **load** — 加载原始网格
2. **repair** — PyMeshLab 修复（非流形、法线、填洞）
3. **scale** — trimesh 缩放到目标包围盒
4. **boolean** — manifold3d 布尔切削（工程接口）
5. **validate** — 质量校验（watertight、体积、包围盒）
6. **export** — GLB/STL/3MF 导出
7. **printability** — 可打印性评分

每个子步骤通过 `dispatch_custom_event("job.post_processing", {step, step_status, message, progress})` 发送 SSE 事件。

不拆成独立节点的理由：子步骤间没有分支逻辑，拆分只增加图复杂度。

### 4. SSE 事件统一

| 原 organic 事件 | 统一后事件名 | 触发节点 |
|---|---|---|
| `analyzing` | `job.organic_spec_ready` | `analyze_organic_node` |
| `generating` | `job.generating` (stage=mesh_generation) | `generate_organic_mesh_node` |
| `post_processing` | `job.post_processing` (step=*) | `postprocess_organic_node` |
| `completed` | `job.completed` | `finalize_node` |
| `failed` | `job.failed` | 任意节点 |

### 5. HITL 确认

organic 经过 `confirm_with_user` 时中断。前端展示确认界面：

- 翻译后的英文 prompt
- 形状分类（shape_category）
- 建议包围盒 vs 用户指定包围盒
- 工程切割列表预览
- 质量模式 + Provider 选择

确认请求复用现有 `ConfirmRequest`，通过 `confirmed_params` 传递 organic 特有参数。

### 6. API 统一

前端 organic 页面改为调用 `/api/v1/jobs`（`input_type="organic"`），不再调用 `/api/v1/organic`。

`CreateJobRequest` 扩展 organic 字段：
```python
class CreateJobRequest(BaseModel):
    input_type: str = "text"
    text: str = ""
    prompt: str = ""
    provider: str = "auto"
    quality_mode: str = "standard"
    reference_image: str | None = None  # 新增：上传的 file_id
    pipeline_config: dict[str, Any] = Field(default_factory=dict)
```

图片上传复用 `/api/v1/jobs/upload` 或保持 organic 专用上传端点（MIME 白名单不同）。

### 7. DB 统一

- organic Job 记录写入统一的 `JobModel` 表（`input_type="organic"`）
- `finalize_node` 扩展：当 `input_type=organic` 时，将 `organic_result` 写入 `result` JSON 列
- `OrganicJobModel` 表保留只读（兼容旧数据查询），不再写入新数据

### 8. 清理

| 文件 | 动作 |
|---|---|
| `backend/api/v1/organic.py` | 删除 |
| `backend/models/organic_job.py` | 保留只读 |
| `backend/graph/nodes/analysis.py` | `stub_organic_node` → `analyze_organic_node` |
| `backend/graph/nodes/organic.py` | 新建 |
| `backend/graph/builder.py` | 更新拓扑 |
| `backend/graph/routing.py` | 扩展路由 |
| `backend/graph/state.py` | 扩展字段 |
| `backend/api/v1/jobs.py` | 扩展 CreateJobRequest |
| `frontend/.../OrganicWorkflow.tsx` | 改调 /api/v1/jobs，改监听 job.* 事件 |

---

## 测试策略

**单元测试**：
- `test_analyze_organic_node` — mock OrganicSpecBuilder
- `test_generate_organic_mesh_node` — mock MeshProvider
- `test_postprocess_organic_node` — mock MeshPostProcessor
- `test_route_after_confirm_organic` — 验证路由

**集成测试**：
- input_type=organic 全图端到端（mock Provider）
- HITL 中断 → resume → 验证事件序列

**前端 E2E**：
- 现有 organic E2E 适配新 API 端点

---

## 验收标准

- [ ] `POST /api/v1/jobs` input_type=organic 返回 SSE 流，含 `job.organic_spec_ready`
- [ ] HITL 中断后 `POST /api/v1/jobs/{id}/confirm` 恢复执行
- [ ] 后处理 5 个子步骤各发 `job.post_processing` 事件
- [ ] `job.completed` 含 model_url、stl_url、threemf_url、mesh_stats
- [ ] `/api/v1/organic` 端点已删除
- [ ] 前端 organic 页面通过 `/api/v1/jobs` 完成全流程
- [ ] `uv run pytest tests/ -v` 全部通过
- [ ] `cd frontend && npx tsc --noEmit && npm run lint` 零错误
