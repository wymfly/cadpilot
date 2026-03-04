## Context

CADPilot 使用 LangGraph 双管道架构（precision + organic），通过 `@register_node` + `DependencyResolver` 实现节点自动发现和编排。后端已具备完整的 config_schema（Pydantic → JSON Schema）、策略注册（strategies）、fallback chain 等能力，但前端 CustomPanel 仅渲染 enabled/strategy 两个字段，大量配置能力被浪费。

当前节点 enabled/disabled 在编译时过滤（`resolver.py` 的 `resolve_all()`），导致配置不可在 HITL 中断时动态调整。

详细设计见 brainstorming 产出：[`docs/plans/2026-03-04-pipeline-config-fullstack-design.md`](../../docs/plans/2026-03-04-pipeline-config-fullstack-design.md)

## Goals / Non-Goals

**Goals:**
- 整理编译层/解析层/执行层的完整能力矩阵
- 实现运行时节点跳过机制，替代编译时过滤
- 新增策略可用性检测 API
- Schema 驱动的前端配置表单引擎，后端加参数前端自动呈现
- HITL 中断时支持修改后续节点配置
- 前后端配置能力完全一致
- E2E 测试覆盖所有配置场景

**Non-Goals:**
- 运行时修改 fallback chain 顺序（架构改动大，投入产出比低）
- 自定义条件路由（需要 DSL/规则引擎，超出配置范围）
- 运行中实时改配置（LangGraph state mutation 在节点执行中不安全）
- 拖拽编排节点顺序（拓扑由 requires/produces 决定，手动排序无意义）
- 用户自定义预设保存（可后续加，MVP 不需要）

## Decisions

### ADR-1: 节点插拔机制 — 运行时跳过 + include_disabled 参数

**选择**: 运行时跳过（`_wrap_node()` 中检查 `state["pipeline_config"][node]["enabled"]`），`DependencyResolver.resolve_all()` 新增 `include_disabled` 参数（默认 True），图编译时 `include_disabled=True` 保留所有节点，validate 预览时 `include_disabled=False` 过滤禁用节点。

**替代方案**:
1. Per-Job 编译（每个 Job 动态编译子图）— 高内存开销 + 不支持 HITL 中调整
2. 直接删除 resolver enabled 过滤 — 丢失 validate 预览能力

**理由**: `include_disabled` 参数保持向后兼容，图编译用默认值（全部编入），validate 用 `False` 展示有效拓扑。跳过时必须发射 `node.skipped` SSE 事件和 trace 条目，确保前端时间线和可观测性不丢失。

### ADR-2: 参数 UI 模式 — Schema 驱动

**选择**: 完整 Schema 驱动（`config_schema` JSON Schema → 前端自动渲染 Ant Design 控件）

**替代方案**: 手写表单（每个节点单独写 React 组件）、混合模式

**理由**: 一劳永逸，后端加参数前端自动呈现。Pydantic v2 的 `model_json_schema()` 原生输出 description/minimum/maximum，`json_schema_extra` 支持 x-group；仅 `x-sensitive` 需后处理注入。类型映射：boolean→Switch, integer/number→InputNumber/Slider, string+enum→Select, x-sensitive→Password, object/array→只读 JSON 显示。

### ADR-3: 配置时机 — Job 创建前 + HITL 中断时（通过 resume_data）

**选择**: 两个配置窗口：Job 创建前完整配置 + HITL 中断时修改后续节点。HITL 配置更新通过 `resume_data`（包含在 `Command(resume=...)` 内）传递，由 `confirm_with_user_node` 读取并 deep-merge 到 state，确保原子性状态转换。

**替代方案**:
1. 仅创建前（灵活性不足）
2. 全程可调（LangGraph state mutation 不安全）
3. `aupdate_state` 先更新再 resume — 存在竞态条件（update 和 resume 之间其他操作可能修改 state）

**理由**: `resume_data` 方式在单次 `Command(resume=...)` 调用内完成所有状态变更，无竞态风险。`confirm_with_user_node` 负责解包 resume_data 中的 `pipeline_config_updates` 并返回 merged state。

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|---------|
| Schema 驱动表单可能无法覆盖复杂 UI 需求（如联动字段） | v1 对 object/array 类型渲染只读 JSON，保留 `x-group` + `json_schema_extra` 扩展点，未来按需添加自定义渲染器 |
| 运行时跳过可能导致下游节点收到不完整的 state | `POST /pipeline/validate` 在配置变更时实时校验拓扑合法性；全部禁用时返回 `valid: false` |
| HITL 中调参增加 confirm 端点复杂度 | `pipeline_config_updates` 为可选字段，通过 `resume_data` 传递，confirm 端点在 resume 前做拓扑校验 |
| x-sensitive 标记仅为 UI 提示，不提供后端安全保障 | SSE event 中对 x-sensitive 字段值做 mask（显示 `"***"`），文档明确标注为 UI-only |
| 旧 API deprecation 可能影响外部调用方 | 仅添加 Deprecated header，不立即删除，前端切换完成后再评估 |
| ValidationBanner 快速切换可能产生竞态响应 | 使用 AbortController 取消进行中的请求，300ms debounce 减少调用频率 |
