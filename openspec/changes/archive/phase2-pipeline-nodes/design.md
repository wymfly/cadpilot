## Context

Phase 0（架构骨架）完成了双通道基础设施：策略注册、fallback_chain、NeuralStrategy 基类、NodeContext、DependencyResolver。Phase 1（mesh_healer）验证了完整的双通道节点模式。

当前 organic 管线存在两套并行机制：
- **Legacy 三节点**：`analyze_organic → generate_organic_mesh → postprocess_organic`（7 步内联处理）
- **New-mode 四节点**：`mesh_healer ✅ → mesh_scale(stub) → boolean_cuts(stub) → export_formats(stub)`

Phase 2 需要统一为新架构，替换所有 stub 节点，废弃 legacy 单体节点。

详细设计参见 brainstorming 产出：`docs/plans/2026-03-03-phase2-unified-design.md`

## Goals / Non-Goals

**Goals:**

- 完成 organic 管线全部节点的真实实现（generate_raw_mesh、mesh_scale、boolean_assemble、slice_to_gcode）
- 建立格式转换基础设施，支持任意节点后按需导出产物
- 废弃 legacy postprocess_organic_node 和 AutoProvider
- 所有新节点遵循 mesh_healer 验证的策略模式

**Non-Goals:**

- Phase 3 节点（apply_lattice、orientation_optimizer、thermal_simulation、generate_supports）
- SPAR3D/TRELLIS 模型部署文档（运维侧）
- 前端导出 UI 改造
- mesh_scale 多策略支持（均匀缩放已满足当前需求）
- API 鉴权/授权机制（新 export 端点遵循现有 API 安全模式，全局 authn/authz 是独立议题）

## Decisions

### D1: 三层架构模型

**决策**：节点按目的区分（Layer 1），策略按功能区分（Layer 2），同一模型的 SaaS/本地部署由配置决定（Layer 3）。

**替代方案**：原设计文档的 algorithm/neural 二分法 — 对 generate_raw_mesh（全是 AI 模型）和 boolean_assemble（全是算法）不适用，通用性不足。

**理由**：三层分离使得添加新模型只改策略层，切换部署方式只改配置层，LangGraph 图层完全不感知。

### D2: export_formats 从管线移除

**决策**：删除 export_formats 节点，格式转换（GLB/STL/3MF 互转）下沉为基础设施工具函数 + API 端点。

**替代方案 1**：保留为管线节点 — 违反"节点=目的"原则（格式转换不改变数据本身）。
**替代方案 2**：合并到 slice_to_gcode — 违反单一职责（导出 vs 切片是不同目的）。

**理由**：管线应以节点为导出时机，用户可在任意节点后导出中间产物送入专业工具加工。格式转换是通用服务，不属于管线数据转换链路。

### D3: generate_raw_mesh 策略=模型选择

**决策**：每个 3D 生成模型（Hunyuan3D、Tripo3D、SPAR3D、TRELLIS）注册为独立策略，策略内部按配置选择 SaaS 或本地部署。

**替代方案 1**：新建独立节点（generate_organic_mesh + generate_raw_mesh 共存）— 两个节点做同一件事，违反节点=目的。
**替代方案 2**：统一为单一 Neural 策略（内部 provider 参数切换）— 无法利用 fallback_chain 在模型间 failover。

**理由**：复用现有 MeshProvider 代码（TripoProvider/HunyuanProvider）作为策略内部的 SaaS 适配器，新模型（SPAR3D/TRELLIS）添加本地适配器。AutoProvider 被 fallback_chain 替代。

### D4: 串行实施顺序

**决策**：导出基础设施 → mesh_scale → boolean_assemble → generate_raw_mesh → slice_to_gcode → 集成验证。

**理由**：导出基础设施先行为后续所有节点测试提供工具；mesh_scale 在 boolean_assemble 前实施（因 boolean_assemble requires=["scaled_mesh"]）；generate_raw_mesh 改造面最大放中段降低风险；slice_to_gcode 最后实施因其依赖已有 mesh 产物。旧节点（export_formats、boolean_cuts）在替代品就绪后一并删除。

## Risks / Trade-offs

- **[Legacy 兼容风险]** generate_organic_mesh 重构可能影响 builder_legacy.py 路径 → 保留 generate_organic_mesh_node 为适配器函数（CadJobState → NodeContext 桥接），不是直接委托（签名不兼容会崩溃）
- **[PrusaSlicer 外部依赖]** slice_to_gcode 依赖 CLI 安装，CI 环境可能缺失 → check_available() 检测 `which prusa-slicer`，未安装时策略标记 unavailable
- **[SSE 事件兼容]** generate_raw_mesh 迁移 NodeContext 后 SSE 事件格式可能变化 → 保持 `job.generating` 事件 payload 不变，通过 ctx.dispatch_progress() 桥接
- **[流形校验性能]** boolean_assemble 的体素化修复是 CPU 密集操作 → asyncio.to_thread() 避免阻塞，voxel_resolution 可配置
