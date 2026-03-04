# 管线配置全功能补全设计

> **目标**：基于 LangGraph 双管道架构，一次性补全管线配置的全栈能力——编译时 vs 运行时的完整能力矩阵、Schema 驱动的前端配置 UI、后端 API 增强、HITL 中调参、策略可用性检测，以及 e2e 验证。

---

## 决策记录

| 决策 | 选择 | 替代方案 | 理由 |
|------|------|---------|------|
| ADR-1: 节点插拔机制 | 运行时跳过（方案 A） | Per-Job 编译（方案 B） | 零编译开销，支持 HITL 中调整，改动最小 |
| ADR-2: 参数 UI 模式 | 完整 Schema 驱动 | 手写表单 / 混合 | 一劳永逸，后端加参数前端自动呈现 |
| ADR-3: 配置时机 | Job 创建前 + HITL 中断时 | 仅创建前 / 全程可调 | 平衡灵活性与复杂度 |

---

## 一、能力矩阵

### LangGraph 三层架构

| 层 | 时机 | 内容 | 可变性 |
|---|---|---|---|
| **编译层** | 应用启动 | 节点拓扑、条件路由、拦截链、fallback chain | 固定，不可运行时修改 |
| **解析层** | Job 创建时 | 预设展开、配置验证、拓扑推导 | 每 Job 不同 |
| **执行层** | 节点运行时 | 策略选择、参数读取、enabled 跳过 | 每 Job 不同，HITL 中可调 |

### 配置维度全表

| 维度 | 分类 | 配置方式 | 生效时机 | 后端状态 | 前端状态 | 本次变更 |
|------|------|---------|---------|---------|--------|---------|
| 节点启用/禁用 | 运行时跳过 | `{node: {enabled: false}}` | 每 Job | ✅ | ✅ Switch | 改为运行时跳过 |
| 策略选择 | 运行时选择 | `{node: {strategy: "x"}}` | 每 Job | ✅ | ✅ Select | 无变更 |
| 策略可用性 | 只读查询 | GET API | 实时 | ❌ | ❌ | **新增** |
| 节点参数 | 运行时注入 | `{node: {timeout: 180}}` | 每 Job | ✅ | ❌ | **新增 Schema 表单** |
| 预设管理 | 展开到节点级 | `{preset: "fast"}` | 每 Job | ✅ | ✅ Segmented | 无变更 |
| 拓扑验证 | 实时校验 | POST validate | 配置变更时 | ✅ | ❌ | **接入前端** |
| HITL 中调参 | state merge | confirm 扩展 | 中断恢复时 | ❌ | ❌ | **新增** |
| fallback chain | 只读展示 | 节点描述符 | 编译时固定 | ✅ | ❌ | **前端展示** |

---

## 二、后端变更

### 2.1 运行时跳过机制

**变更文件**: `backend/graph/builder.py`

当前 `enabled=false` 在 resolver 编译时过滤。改为：

- **编译时**：全节点编译进图（resolver 不再按 enabled 过滤）
- **运行时**：`_wrap_node()` 中检查 `state["pipeline_config"][node]["enabled"]`，为 false 时返回空 dict

```python
# _wrap_node() 增强
async def _wrapped(state: CadJobState) -> dict:
    node_cfg = state.get("pipeline_config", {}).get(node_name, {})
    if not node_cfg.get("enabled", True):
        logger.info("Node %s skipped (disabled)", node_name)
        return {}
    # ... 原有执行逻辑
```

**注意**：`POST /pipeline/validate` 仍按 enabled 过滤计算拓扑（预览用途），不影响编译。

### 2.2 策略可用性端点

**新增端点**: `GET /api/v1/pipeline/strategy-availability`

```python
@router.get("/strategy-availability")
async def get_strategy_availability():
    """返回每个节点每个策略的可用性状态。"""
    result = {}
    for name, desc in registry.all().items():
        if not desc.strategies:
            continue
        avail = {}
        for s_name, s_cls in desc.strategies.items():
            try:
                instance = s_cls(config=BaseNodeConfig())
                available = instance.check_available()
                avail[s_name] = {"available": available}
                if not available:
                    avail[s_name]["reason"] = getattr(instance, "unavailable_reason", "依赖未满足")
            except Exception as exc:
                avail[s_name] = {"available": False, "reason": str(exc)}
        result[name] = avail
    return result
```

### 2.3 config_schema 增强

**变更文件**: `backend/graph/registry.py`

从 Pydantic config_model 的 Field metadata 提取：
- `description` → schema `description`
- `ge` / `le` → schema `minimum` / `maximum`
- `json_schema_extra` 中的 `x-group`（如 "基本"/"高级"）
- 字段名含 `api_key` / `secret` / `password` → `x-sensitive: true`

### 2.4 confirm 端点扩展

**变更文件**: `backend/api/v1/jobs.py`

```python
class ConfirmRequest(BaseModel):
    confirmed_params: dict | None = None
    confirmed_spec: dict | None = None
    base_body_method: str | None = None
    disclaimer_accepted: bool | None = None
    pipeline_config_updates: dict[str, dict] | None = None  # 新增
```

Resume graph 前 deep-merge:
```python
if body.pipeline_config_updates:
    current = state.get("pipeline_config", {})
    for node, updates in body.pipeline_config_updates.items():
        current.setdefault(node, {}).update(updates)
    # 更新 state 中的 pipeline_config
```

### 2.5 旧 API 清理

- `GET /pipeline/presets`（旧版 PipelineConfig 预设）→ 添加 `Deprecated` header
- `GET /pipeline/tooltips`（旧版字段提示）→ 添加 `Deprecated` header
- 不立即删除，前端不再调用即可

---

## 三、前端 UI 架构

### 3.1 组件层级

```
PipelineConfigBar (已有容器，重构)
├── PresetSelector (已有: fast/balanced/full_print/custom)
├── ValidationBanner (新增: 实时验证结果展示)
└── CustomPanel (重构: 从列表改为卡片式)
    └── NodeConfigCard[] (每个节点一张折叠卡片)
        ├── Header: [Switch enabled] [节点名] [策略 Select]
        │   └── 策略不可用时: 灰化 + Tooltip("API Key 未配置")
        ├── SchemaForm (新增: 根据 config_schema 动态渲染)
        │   ├── boolean → Switch
        │   ├── integer/number → InputNumber 或 Slider(有 min/max)
        │   ├── string + enum → Select
        │   ├── string(无 enum) → Input
        │   └── x-sensitive → Input.Password
        └── FallbackChainTag (新增: Tag 列表展示 fallback 顺序)

HITL ConfirmDialog (已有，扩展)
└── Collapse "高级配置"
    └── 复用 NodeConfigCard[]（仅展示后续未执行的节点）
```

### 3.2 Schema 驱动表单引擎 — SchemaForm

**新增文件**: `frontend/src/components/SchemaForm/index.tsx`

核心逻辑：
1. 接收 `config_schema: JSONSchema` + `value: Record<string, unknown>` + `onChange`
2. 遍历 `properties`，按 `x-group` 分组
3. 每个属性根据 type/enum/format 选择渲染控件
4. 跳过 `enabled` 和 `strategy`（由 NodeConfigCard header 渲染）
5. `x-sensitive` 字段用 Password 输入框

### 3.3 ValidationBanner

**新增文件**: `frontend/src/components/PipelineConfigBar/ValidationBanner.tsx`

- 监听 config 变更，debounce 300ms 后调用 `POST /pipeline/validate`
- 有效：绿色 ✓ + 节点数 + 拓扑信息
- 无效：红色 ✗ + 具体错误原因（如 "generate_raw_mesh 的依赖 mesh_healer 已禁用"）

### 3.4 数据流

```
用户操作 → nodeConfig state 更新
  → debounce 300ms → POST /pipeline/validate
  → ValidationBanner 更新
  → 用户点击创建
  → POST /jobs({..., pipeline_config: nodeConfig})
```

HITL 场景：
```
HITL 中断 → 展示 confirm 对话框
  → 用户修改后续节点配置
  → POST /jobs/{id}/confirm({
      confirmed_params: {...},
      pipeline_config_updates: {node: {strategy: "new"}}
    })
  → graph resume with merged config
```

### 3.5 策略可用性集成

- 页面加载时 `GET /pipeline/strategy-availability`
- 缓存到 PipelineConfigBar state
- NodeConfigCard 的策略 Select 中：不可用选项 `disabled + Tooltip`

---

## 四、测试策略

### 4.1 后端单元测试

| 测试 | 文件 | 覆盖内容 |
|------|------|---------|
| test_runtime_skip | tests/test_graph_builder.py | enabled=false 节点返回空 dict |
| test_strategy_availability | tests/test_pipeline_config_api.py | mock check_available，验证响应格式 |
| test_confirm_config_merge | tests/test_api_v1.py | HITL confirm 时 pipeline_config 正确合并 |
| test_validate_disabled_core | tests/test_pipeline_config_api.py | 禁用核心节点时 validate 返回无效 |
| test_schema_generation | tests/test_registry.py | config_model → schema 包含 description/min/max |

### 4.2 前端组件测试

| 测试 | 覆盖内容 |
|------|---------|
| SchemaForm renders controls | boolean→Switch, number→InputNumber, enum→Select |
| SchemaForm sensitive fields | x-sensitive→Password |
| ValidationBanner shows error | invalid config → 红色警告 |
| NodeConfigCard strategy disabled | 不可用策略灰化 + tooltip |
| PresetSelector fills config | 选预设 → 所有节点配置填充 |

### 4.3 E2E 测试

| 场景 | 验证内容 |
|------|---------|
| 预设选择 → 创建 Job | 节点按预设参数执行 |
| 禁用节点 → validate | 显示警告 → 启用后创建成功 |
| 自定义参数 → 创建 Job | 节点读取到修改后的参数 |
| 策略灰化 | mock API key 缺失 → tooltip 原因 |
| HITL 中改策略 | confirm 后后续节点用新策略 |

---

## 五、不做的事（YAGNI）

| 不做 | 理由 |
|------|------|
| 运行时修改 fallback chain 顺序 | 架构改动大，投入产出比低 |
| 自定义条件路由 | 需要 DSL/规则引擎，超出配置范围 |
| 运行中实时改配置 | LangGraph state mutation 在节点执行中不安全 |
| 拖拽编排节点顺序 | 拓扑由 requires/produces 决定，手动排序无意义 |
| 节点代码级自定义 | 超出配置范围，属于开发者扩展 |
| 用户自定义预设保存 | 可以后续加，MVP 不需要 |
