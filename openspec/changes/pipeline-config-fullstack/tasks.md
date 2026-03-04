## 任务拓扑

```
[T1 || T2 || T3] → T4 → T5 → [T6 || T7] → T8 → T9 → T10 → T11
```

- T1/T2/T3：后端三组独立任务（文件无交叉），可完全并行
- T4：confirm 端点扩展 + 旧 API 废弃标记
- T5：前端类型与 API 对齐（T6/T7 的前置）
- T6/T7：前端两组独立任务（SchemaForm 和 NodeConfigCard），可并行
- T8：ValidationBanner（依赖 T7 的 PipelineConfigBar 容器）
- T9：HITL ConfirmDialog（依赖 T4 的 confirm 端点 + T7 的 NodeConfigCard）
- T10：E2E 测试（依赖所有前端后端完成）

---

## 1. 后端：运行时节点跳过 [backend]

**文件**: `builder.py`, `resolver.py`, `tests/test_runtime_skip.py`

- [ ] 1.1 修改 `_wrap_node()` 添加 enabled 检查：在 `builder.py:108-180` 的 `wrapped()` 函数中，`node.started` SSE 事件发射后检查 `state.get("pipeline_config", {}).get(node_name, {}).get("enabled", True)`，为 false 时发射 `node.skipped` SSE 事件 + trace 条目，然后返回 `{}` 不执行策略逻辑
- [ ] 1.2 修改 `DependencyResolver.resolve_all()` 添加 `include_disabled: bool = True` 参数：默认不过滤（全编入图），`False` 时按 `pipeline_config` 过滤（用于 validate 预览）
- [ ] 1.3 修改 `POST /pipeline/validate` 端点使用 `resolve_all(include_disabled=False)`，增加全部禁用时返回 `{"valid": false, "error": "至少需要启用一个节点"}`
- [ ] 1.4 编写测试 `test_runtime_skip`：mock 节点 enabled=false，验证 `_wrap_node()` 发射 `node.skipped` 事件 + 返回空 dict
- [ ] 1.5 编写测试 `test_resolver_include_disabled`：验证 `resolve_all(include_disabled=True)` 包含 disabled 节点，`include_disabled=False` 排除

## 2. 后端：策略可用性 API [backend]

**文件**: `pipeline_config.py`, `tests/test_strategy_availability.py`

- [ ] 2.1 在 `pipeline_config.py` 新增 `GET /pipeline/strategy-availability` 端点：遍历 registry 所有节点的 strategies，用 `config=desc.config_model()` 实例化策略后调用 `check_available()`，返回 `{node: {strategy: {available, reason}}}`
- [ ] 2.2 编写测试 `test_strategy_availability`：mock `check_available()` 返回 true/false，验证响应格式正确且使用 config_model 实例
- [ ] 2.3 编写测试 `test_strategy_availability_error`：mock 策略实例化抛异常，验证返回 `{available: false, reason: "..."}`

## 3. 后端：config_schema x-sensitive 后处理 [backend]

**文件**: `registry.py`, `tests/test_schema_sensitive.py`

- [ ] 3.1 在 `registry.py` 添加 `enhance_config_schema()` 函数：对 `model_json_schema()` 的输出做后处理，字段名含 `api_key`/`secret`/`password` 时注入 `x-sensitive: true`（Pydantic v2 原生已输出 description/minimum/maximum/x-group，无需自定义提取）
- [ ] 3.2 在 `/nodes` 端点调用 `enhance_config_schema()` 后返回
- [ ] 3.3 编写测试 `test_schema_sensitive`：创建含 `api_key` 字段的 config_model，验证 `x-sensitive: true` 被注入；验证 description/minimum/maximum/x-group 由 Pydantic v2 原生输出

## 4. 后端：confirm 端点扩展 + 旧 API 废弃 [backend]

**文件**: `jobs.py`, `pipeline_config.py`, `tests/test_confirm_config.py`

- [ ] 4.1 在 `ConfirmRequest`（`jobs.py:113-120`）中新增 `pipeline_config_updates: dict[str, dict] | None = None` 字段
- [ ] 4.2 在 `confirm_job()` 端点（`jobs.py:579-665`）中，将 `pipeline_config_updates` 包含在 `resume_data` 内传给 `Command(resume=...)`，不使用 `aupdate_state`
- [ ] 4.3 在 `confirm_with_user_node` 中处理 `resume_data` 中的 `pipeline_config_updates`：deep-merge 到 state 的 `pipeline_config` 并返回
- [ ] 4.4 confirm 端点 resume 前调用内部 validate 逻辑校验合并后的拓扑，失败返回 HTTP 400
- [ ] 4.5 为 `GET /pipeline/presets` 和 `GET /pipeline/tooltips` 添加 `Deprecation` 和 `Sunset` 响应头
- [ ] 4.6 编写测试 `test_confirm_config_merge`：验证 `pipeline_config_updates` 通过 resume_data 传递并正确合并到 state
- [ ] 4.7 编写测试 `test_confirm_invalid_config`：验证 pipeline_config_updates 导致无效拓扑时返回 400

## 5. 前端：类型与 API 对齐 [frontend]

**文件**: `types/pipeline.ts`, `services/api.ts`

- [ ] 5.1 在 `types/pipeline.ts` 新增 `StrategyAvailability` 接口，与后端响应对齐
- [ ] 5.2 在 `types/pipeline.ts` 的 `PipelineNodeDescriptor` 中添加 `fallback_chain?: string[]`
- [ ] 5.3 在 `services/api.ts` 添加 `getStrategyAvailability()` 函数
- [ ] 5.4 `tsc --noEmit` + lint 通过

## 6. 前端：SchemaForm 组件 [frontend]

**文件**: `components/SchemaForm/index.tsx`, `components/SchemaForm/__tests__/`

- [ ] 6.1 创建 `SchemaForm` 组件：接收 `config_schema` + `value` + `onChange`，按 type 映射渲染控件（boolean→Switch, integer+min/max→Slider, integer→InputNumber, string+enum→Select, string→Input, x-sensitive→Password, object/array→只读 JSON Text）
- [ ] 6.2 实现 `x-group` 分组渲染：按 `x-group` 值分组字段，每组一个折叠区域
- [ ] 6.3 跳过 `enabled` 和 `strategy` 字段（由 NodeConfigCard header 渲染）
- [ ] 6.4 编写组件测试：验证各类型控件正确渲染、sensitive 字段用 Password、分组正确、unsupported 类型显示只读

## 7. 前端：NodeConfigCard 重构 [frontend]

**文件**: `components/PipelineConfigBar/CustomPanel.tsx`, `components/PipelineConfigBar/index.tsx`

- [ ] 7.1 重构 `CustomPanel.tsx` 从列表改为卡片式：每个节点一张折叠卡片（Ant Design Collapse）
- [ ] 7.2 卡片 Header：`[Switch enabled] [节点名] [策略 Select]`，策略不可用时 `disabled + Tooltip`
- [ ] 7.3 卡片 Body：集成 SchemaForm（动态参数表单）+ FallbackChainTag（fallback chain 顺序展示）
- [ ] 7.4 集成策略可用性：页面加载时调用 `GET /pipeline/strategy-availability`，缓存到 state，策略 Select 中不可用选项 disabled + Tooltip 提示原因

## 8. 前端：ValidationBanner [frontend]

**文件**: `components/PipelineConfigBar/ValidationBanner.tsx`

- [ ] 8.1 创建 `ValidationBanner.tsx`：监听 config 变更，debounce 300ms 后调用 `POST /pipeline/validate`，使用 `AbortController` 取消进行中的请求
- [ ] 8.2 有效时显示绿色 ✓ + 节点数 + 拓扑；无效时红色 ✗ + 错误原因
- [ ] 8.3 集成到 PipelineConfigBar 容器（`index.tsx`），放在 PresetSelector 和 CustomPanel 之间

## 9. 前端：HITL ConfirmDialog 扩展 [frontend]

**文件**: `pages/Generate/GenerateWorkflow.tsx`, `contexts/GenerateWorkflowContext.tsx`

- [ ] 9.1 在 ConfirmDialog 中添加 Collapse "高级配置" 区域，复用 NodeConfigCard（仅展示后续未执行的节点）
- [ ] 9.2 confirm 前调用 `POST /pipeline/validate` 校验合并后的配置
- [ ] 9.3 confirm 请求中包含 `pipeline_config_updates` 字段

## 10. E2E 测试 [test:e2e]

**文件**: `frontend/e2e/pipeline-config.spec.ts`

- [ ] 10.1 测试：禁用节点 → validate API 返回有效拓扑（不含该节点）→ Job 创建 → 该节点跳过（SSE 收到 node.skipped 事件）
- [ ] 10.2 测试：全部禁用 → validate API 返回 `valid: false` → 创建按钮 disabled
- [ ] 10.3 测试：自定义参数 → SchemaForm 修改 → validate 通过 → 创建 Job → 后端节点读取到修改后的参数值
- [ ] 10.4 测试：策略灰化 — mock strategy-availability API 返回 unavailable → 策略 Select 对应选项 disabled + Tooltip 展示原因
- [ ] 10.5 测试：HITL 中改策略 → 前端 validate 通过 → confirm 带 pipeline_config_updates → 后续节点用新策略执行
