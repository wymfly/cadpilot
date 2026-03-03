## MODIFIED Requirements

### Requirement: Organic pipeline topology
Organic input_type 的管线拓扑 SHALL 更新为：`generate_raw_mesh → mesh_healer → mesh_scale → boolean_assemble → [slice_to_gcode] → finalize`。`export_formats` 节点从管线中移除。

#### Scenario: Resolver produces correct order
- **WHEN** DependencyResolver 为 input_type="organic" 解析管线
- **THEN** 节点执行顺序为 generate_raw_mesh → mesh_healer → mesh_scale → boolean_assemble → slice_to_gcode → finalize

#### Scenario: export_formats removed from pipeline
- **WHEN** DependencyResolver 为 input_type="organic" 解析管线
- **THEN** export_formats 不出现在执行顺序中

#### Scenario: slice_to_gcode optional
- **WHEN** PrusaSlicer 和 OrcaSlicer 均未安装
- **THEN** slice_to_gcode 节点的所有策略 check_available()=False，节点跳过

## REMOVED Requirements

### Requirement: export_formats pipeline node
**Reason**: 格式转换（GLB/STL/3MF）不改变数据本身，不属于管线数据转换链路。功能下沉为基础设施（mesh-format-export capability）。
**Migration**: 使用 `GET /api/jobs/{id}/assets/{key}?format=stl` 端点按需导出，替代管线内的格式转换节点。
