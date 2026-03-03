## ADDED Requirements

### Requirement: Mesh scale node implementation
`mesh_scale` 节点 SHALL 从 stub 替换为真实均匀缩放实现，requires=["watertight_mesh"]，produces=["scaled_mesh"]，input_types=["organic"]。

#### Scenario: Scale to target bounding box
- **WHEN** OrganicSpec.final_bounding_box = (100, 80, 50)
- **THEN** 网格均匀缩放至最大维度适配目标包围盒（mm），保持纵横比

#### Scenario: Post-scale alignment (execution order)
- **WHEN** 缩放完成
- **THEN** 执行顺序为：1) 均匀缩放 → 2) 底面贴合 Z=0（translate Z 使 bbox.min.z = 0）→ 3) XY 质心居中（translate XY 使质心 X=0, Y=0）

### Requirement: Skip when no target size
节点 SHALL 在无目标尺寸时优雅处理。

#### Scenario: No bounding box specified
- **WHEN** OrganicSpec.final_bounding_box 为 None
- **THEN** 将 watertight_mesh 直接传递为 scaled_mesh（不做缩放）

### Requirement: Skip when no input
节点 SHALL 在上游未产出 watertight_mesh 时优雅跳过。

#### Scenario: No watertight_mesh available
- **WHEN** AssetRegistry 中无 watertight_mesh
- **THEN** 设置 `mesh_scale_status=skipped_no_input`，不产出 scaled_mesh
