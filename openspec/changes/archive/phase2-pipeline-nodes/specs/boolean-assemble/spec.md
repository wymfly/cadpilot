## ADDED Requirements

### Requirement: Boolean assemble node registration
`boolean_assemble` 节点 SHALL 注册为策略化节点，替换现有 `boolean_cuts` stub，requires=["scaled_mesh"]，produces=["final_mesh"]，input_types=["organic"]。

#### Scenario: Node registered with correct metadata
- **WHEN** NodeRegistry 完成发现
- **THEN** `registry.get("boolean_assemble")` 返回 descriptor，display_name="布尔装配"，strategies 包含 "manifold3d"

#### Scenario: Replaces boolean_cuts stub
- **WHEN** boolean_assemble 注册成功
- **THEN** boolean_cuts 节点不再存在于 registry 中

### Requirement: Manifold check gate
`Manifold3DStrategy` SHALL 在执行布尔运算前检查输入网格是否为流形网格，非流形时尝试体素化修复。

#### Scenario: Manifold mesh passes directly
- **WHEN** 输入 scaled_mesh 是流形网格
- **THEN** 直接执行布尔运算，不做体素化

#### Scenario: Non-manifold mesh repaired by voxelization
- **WHEN** 输入 scaled_mesh 非流形
- **THEN** 先执行 manifold3d 体素化重采样（分辨率由 config.voxel_resolution 控制），再执行布尔运算

#### Scenario: Voxelization fails with skip_on_non_manifold=False (default)
- **WHEN** 体素化后网格仍非流形，且 config.skip_on_non_manifold = False
- **THEN** 抛出异常，中断管线，节点状态标记为 `failed_non_manifold`（防止生成缺失工程特征的残次品）

#### Scenario: Voxelization fails with skip_on_non_manifold=True
- **WHEN** 体素化后网格仍非流形，且 config.skip_on_non_manifold = True
- **THEN** 跳过布尔运算，将原始 scaled_mesh 作为 final_mesh 传递，并记录警告

#### Scenario: Voxelization retry with increased resolution
- **WHEN** 首次体素化（config.voxel_resolution）后网格仍非流形
- **THEN** 以 2x 分辨率重试一次体素化；若仍失败则按 skip_on_non_manifold 配置处理

### Requirement: Boolean cut operations
系统 SHALL 支持对网格执行 FlatBottomCut、HoleCut、SlotCut 三种布尔切割操作，使用 manifold3d 库。

#### Scenario: Apply flat bottom cut
- **WHEN** engineering_cuts 包含 FlatBottomCut(offset=2.0)
- **THEN** 从网格底部减去厚度为 offset 的平面，生成平底

#### Scenario: Apply hole cut
- **WHEN** engineering_cuts 包含 HoleCut(diameter=5, depth=10, position=(0,0,0), direction="top")
- **THEN** 在指定位置和方向打一个直径 5mm 深度 10mm 的圆柱孔

#### Scenario: Single cut failure does not abort
- **WHEN** 某个切割操作失败（如几何异常）
- **THEN** 跳过该切割，继续执行剩余切割，在 warnings 中记录失败原因，节点状态标记为 `partial_cuts`

#### Scenario: All cuts fail
- **WHEN** 所有切割操作均失败
- **THEN** 抛出异常，中断管线（quality_mode="draft" 时除外，draft 模式下 passthrough 原网格并记录警告）

### Requirement: Skip when no cuts
节点 SHALL 在无工程切割需求时 passthrough 原始网格。

#### Scenario: No engineering_cuts specified
- **WHEN** organic_spec.engineering_cuts 为空或 None
- **THEN** 将 scaled_mesh 直接传递为 final_mesh，不执行流形校验和布尔运算

#### Scenario: Skip on non-manifold configured
- **WHEN** config.skip_on_non_manifold = True 且输入网格非流形
- **THEN** 跳过体素化修复，将原始 scaled_mesh 直接传递为 final_mesh 并记录警告

#### Scenario: Quality mode draft
- **WHEN** organic_spec.quality_mode = "draft"
- **THEN** 跳过布尔运算，将 scaled_mesh 直接传递为 final_mesh（与现有 postprocess_organic_node draft 行为一致）

### Requirement: Skip when no input
节点 SHALL 在上游未产出 scaled_mesh 时优雅跳过。

#### Scenario: No scaled_mesh available
- **WHEN** AssetRegistry 中无 scaled_mesh
- **THEN** 设置 `boolean_assemble_status=skipped_no_input`，不产出 final_mesh

### Requirement: Progress reporting
节点 SHALL 通过 `ctx.dispatch_progress()` 报告处理进度。

#### Scenario: Progress events during execution
- **WHEN** 节点执行包含 3 个切割操作
- **THEN** 依次报告每个切割的进度（如 1/3, 2/3, 3/3）
