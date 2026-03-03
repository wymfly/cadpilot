## ADDED Requirements

### Requirement: Mesh healer node registration
系统 SHALL 注册名为 `mesh_healer` 的节点，替代现有 `mesh_repair` stub。节点 MUST 声明 `requires=["raw_mesh"]`、`produces=["watertight_mesh"]`、`input_types=["organic"]`。

#### Scenario: Node registered in new builder
- **WHEN** 使用 new builder (`USE_NEW_BUILDER=1`) 构建图
- **THEN** 图中包含 `mesh_healer` 节点，不包含 `mesh_repair` 节点

#### Scenario: Legacy builder unaffected
- **WHEN** 使用 legacy builder (`USE_NEW_BUILDER=0`) 构建图
- **THEN** 图中仍使用 `postprocess_organic_node` 路径，不包含 `mesh_healer`

### Requirement: Dual-channel strategy support
mesh_healer MUST 注册两种策略：`algorithm`（AlgorithmHealStrategy）和 `neural`（NeuralHealStrategy），默认策略为 `algorithm`，fallback_chain 为 `["algorithm", "neural"]`。

#### Scenario: User selects algorithm strategy
- **WHEN** `pipeline_config.mesh_healer.strategy` 设为 `"algorithm"`
- **THEN** 系统使用 AlgorithmHealStrategy 执行修复

#### Scenario: User selects neural strategy
- **WHEN** `pipeline_config.mesh_healer.strategy` 设为 `"neural"` 且 neural endpoint 可用
- **THEN** 系统使用 NeuralHealStrategy 通过 HTTP 调用修复

#### Scenario: Auto mode fallback
- **WHEN** `pipeline_config.mesh_healer.strategy` 设为 `"auto"` 且 algorithm 策略执行失败
- **THEN** 系统自动 fallback 到 neural 策略（如果可用）

#### Scenario: Auto mode with neural disabled
- **WHEN** strategy 为 `"auto"` 且 neural 未配置（neural_enabled=false）
- **THEN** 仅尝试 algorithm 策略，neural 不参与 fallback

### Requirement: Algorithm heal strategy escalation
AlgorithmHealStrategy MUST 按缺陷严重度编排多工具升级链：Level 1（trimesh）→ Level 2（PyMeshFix/PyMeshLab）→ Level 3（MeshLib 体素化）。

#### Scenario: Mild defects repaired by trimesh
- **WHEN** mesh 仅有 normals/winding 问题
- **THEN** 使用 trimesh.repair 修复，不调用更高级工具

#### Scenario: Moderate defects escalate to PyMeshFix
- **WHEN** mesh 有孔洞或非流形边，trimesh 修复后验证仍未通过
- **THEN** 升级到 Level 2 使用 PyMeshFix 修复

#### Scenario: Severe defects escalate to MeshLib
- **WHEN** mesh 有自相交或大面积缺失
- **THEN** 使用 MeshLib 体素化重建

#### Scenario: Tool unavailability bypass
- **WHEN** 某级工具未安装（import 失败）
- **THEN** 自动跳到下一级工具

### Requirement: Repair validation
每级修复完成后，系统 MUST 验证修复结果（is_watertight + volume > 0 + 无退化面）。

#### Scenario: Validation passes
- **WHEN** 修复后 mesh is_watertight=True 且 volume > 0
- **THEN** 标记修复成功，输出 watertight_mesh

#### Scenario: Validation fails at current level
- **WHEN** 修复后验证不通过且存在更高级工具
- **THEN** 自动升级到下一级工具

#### Scenario: All levels exhausted
- **WHEN** 所有算法工具修复后验证均不通过
- **THEN** auto 模式尝试 fallback 到 neural；非 auto 模式报错

### Requirement: Neural heal strategy HTTP integration
NeuralHealStrategy MUST 继承 NeuralStrategy 基类，调用 `/v1/repair` HTTP 端点。

#### Scenario: Neural repair success
- **WHEN** NKSR 服务可用且修复成功
- **THEN** 将修复结果存为 watertight_mesh asset，metadata 包含 metrics

#### Scenario: Neural service disabled
- **WHEN** neural_enabled=false 或未配置 endpoint
- **THEN** check_available() 返回 False，该策略不参与执行

#### Scenario: Neural health check failed
- **WHEN** endpoint 已配置但 health check 返回非 200
- **THEN** check_available() 返回 False（degraded 状态）

### Requirement: Optional retopo sub-step
mesh_healer MUST 支持可选的 MeshAnything V2 retopo 子步骤，在修复输出后触发。

#### Scenario: Retopo triggered by high face count
- **WHEN** 修复后 face_count > retopo_threshold 且 retopo.enabled=true
- **THEN** 调用 `/v1/retopo` HTTP 端点进行拓扑重建

#### Scenario: Retopo skipped
- **WHEN** retopo.enabled=false 或 face_count <= retopo_threshold
- **THEN** 跳过 retopo，直接输出修复结果

### Requirement: Asset and progress reporting
mesh_healer MUST 通过 NodeContext API 报告资产和进度。

#### Scenario: Asset output
- **WHEN** 修复完成
- **THEN** 调用 `ctx.put_asset("watertight_mesh", path, format, metadata)` 注册资产

#### Scenario: Progress events
- **WHEN** 修复过程中各阶段完成
- **THEN** 调用 `ctx.dispatch_progress()` 发送 SSE 进度事件（诊断、修复、验证、retopo）

### Requirement: Fallback trace recording
mesh_healer 在 auto 模式下 MUST 通过 `ctx._fallback_trace` 记录策略尝试轨迹。

#### Scenario: Fallback trace populated
- **WHEN** auto 模式执行（无论是否发生 fallback）
- **THEN** node_trace 中包含 fallback 字段，记录 strategies_attempted 和 strategy_used
