## ADDED Requirements

### Requirement: Generate raw mesh node registration
`generate_raw_mesh` 节点 SHALL 注册为策略化节点，替换现有 `generate_organic_mesh`，requires=["confirmed_params"]，produces=["raw_mesh"]，input_types=["organic"]。

#### Scenario: Node registered with strategies
- **WHEN** NodeRegistry 完成发现
- **THEN** `registry.get("generate_raw_mesh")` 返回 descriptor，strategies 包含 "hunyuan3d"、"tripo3d"、"spar3d"、"trellis"，default_strategy="hunyuan3d"

#### Scenario: Fallback chain configured
- **WHEN** 节点注册完成
- **THEN** fallback_chain 为 ["hunyuan3d", "tripo3d", "spar3d", "trellis"]

### Requirement: Strategy = model selection
每个 3D 生成模型 SHALL 注册为独立策略，策略名对应模型名。

#### Scenario: Select specific model via config
- **WHEN** config.strategy = "tripo3d"
- **THEN** 使用 Tripo3DGenerateStrategy 执行生成

#### Scenario: Auto mode with fallback
- **WHEN** config.strategy = "auto"（框架级保留值，触发 fallback_chain 遍历）
- **THEN** 按 fallback_chain 顺序尝试，第一个 check_available()=True 的策略执行

### Requirement: Dual deployment per strategy
每个策略 SHALL 支持 SaaS API 和/或本地 HTTP endpoint 两种部署方式，由配置决定。

#### Scenario: Hunyuan3D via SaaS
- **WHEN** config 中 hunyuan3d_api_key 已配置，hunyuan3d_endpoint 未配置
- **THEN** 使用 SaaS API（复用现有 HunyuanProvider）

#### Scenario: Hunyuan3D via local endpoint
- **WHEN** config 中 hunyuan3d_endpoint 已配置
- **THEN** 使用本地 HTTP endpoint（POST /v1/generate），优先于 SaaS

#### Scenario: Both endpoint and api_key configured
- **WHEN** config 中 hunyuan3d_endpoint 和 hunyuan3d_api_key 均已配置
- **THEN** 优先使用本地 endpoint；本地 endpoint 不健康或执行失败时回退到 SaaS API

#### Scenario: Local endpoint unhealthy with SaaS fallback
- **WHEN** hunyuan3d_endpoint 已配置但 health check 失败，hunyuan3d_api_key 已配置
- **THEN** check_available() 返回 True（SaaS 可用），execute() 使用 SaaS API

#### Scenario: SPAR3D local only
- **WHEN** config 中 spar3d_endpoint 已配置
- **THEN** 使用本地 HTTP endpoint 生成网格

#### Scenario: Strategy unavailable
- **WHEN** 策略的 API key 和 endpoint 均未配置
- **THEN** check_available() 返回 False，auto 模式跳过该策略

### Requirement: Local endpoint health check
本地部署策略 SHALL 通过 HTTP health check 验证 endpoint 可用性。

#### Scenario: Local endpoint healthy
- **WHEN** GET {endpoint}/health 返回 200
- **THEN** check_available() 返回 True

#### Scenario: Local endpoint unreachable (local-only strategy)
- **WHEN** GET {endpoint}/health 超时或返回非 200，且该策略无 SaaS 回退（如 SPAR3D、TRELLIS）
- **THEN** check_available() 返回 False，auto 模式 fallback 到下一个策略

#### Scenario: Local endpoint unreachable (dual-deploy strategy)
- **WHEN** GET {endpoint}/health 超时或返回非 200，但该策略配置了 SaaS api_key（如 Hunyuan3D）
- **THEN** check_available() 返回 True（SaaS 可用），execute() 使用 SaaS API

### Requirement: SaaS provider reuse
SaaS 策略 SHALL 复用现有 `MeshProvider` 实现（TripoProvider、HunyuanProvider），不重写 SaaS 通信逻辑。

#### Scenario: TripoProvider wrapped as strategy
- **WHEN** Tripo3DGenerateStrategy.execute() 被调用
- **THEN** 内部实例化 TripoProvider 并调用 provider.generate()

### Requirement: Generation timeout
策略 SHALL 支持超时控制，超时后触发 fallback。

#### Scenario: Generation timeout triggers fallback
- **WHEN** 模型生成超过 config.timeout 秒
- **THEN** 取消当前请求，auto 模式 fallback 到 fallback_chain 中的下一个策略

#### Scenario: Generation runtime error triggers fallback
- **WHEN** 模型生成过程中发生运行时错误（非超时，如 HTTP 500、连接中断）
- **THEN** auto 模式 fallback 到 fallback_chain 中的下一个策略，非 auto 模式报错

#### Scenario: All strategies exhausted
- **WHEN** 所有策略均失败（超时、运行时错误或不可用）
- **THEN** 节点报错，job 状态标记为 failed

### Requirement: Legacy compatibility
系统 SHALL 保留 `generate_organic_mesh_node` 作为函数别名（非节点注册）。

#### Scenario: Legacy builder still works
- **WHEN** builder_legacy.py 导入 generate_organic_mesh_node 并以 `(state: CadJobState)` 签名调用
- **THEN** 适配器函数将 CadJobState 封装为 NodeContext，委托给 generate_raw_mesh_node，再将产物同步回 state

#### Scenario: No duplicate node registration
- **WHEN** generate_raw_mesh 已注册
- **THEN** generate_organic_mesh_node 不通过 @register_node 注册，仅作为 Python 函数别名，避免 NodeRegistry asset conflict

### Requirement: NodeContext migration
节点 SHALL 使用 NodeContext 签名（而非 CadJobState），通过 AssetRegistry 传递产物。

#### Scenario: Raw mesh stored as asset
- **WHEN** 生成成功
- **THEN** ctx.put_asset("raw_mesh", path, format) 被调用，format 根据实际文件后缀推导或使用 config.output_format

#### Scenario: SSE progress events
- **WHEN** 模型生成进行中
- **THEN** 通过 ctx.dispatch_progress() 报告进度，事件格式与现有 job.generating 兼容
