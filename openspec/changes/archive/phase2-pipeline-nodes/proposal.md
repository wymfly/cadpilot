## Why

Phase 0（架构骨架）和 Phase 1（mesh_healer 双通道节点）已完成，管线基础设施（策略注册、fallback_chain、NeuralStrategy 基类、NodeContext）已验证可用。当前 organic 管线仍有 3 个 stub 节点（mesh_scale、boolean_cuts、export_formats）和 1 个 legacy 单体节点（postprocess_organic_node），需要替换为真实实现以完成端到端 3D 打印管线。

## What Changes

- **替换 `generate_organic_mesh`** → `generate_raw_mesh`：从 legacy CadJobState 签名迁移到 NodeContext + 策略模式，支持多模型（Hunyuan3D/Tripo3D/SPAR3D/TRELLIS）+ 双部署（SaaS API / 本地 HTTP endpoint，由配置决定）
- **替换 `boolean_cuts` stub** → `boolean_assemble`：提取现有 `MeshPostProcessor.apply_boolean_cuts()` 逻辑到独立策略节点，新增流形校验门（is_manifold → 体素化修复 → 重试）
- **删除 `export_formats` 节点**：格式转换（GLB/STL/3MF 互转）下沉为基础设施工具函数 + API 端点，管线任意节点后可按需导出产物
- **新增 `slice_to_gcode` 节点**：PrusaSlicer/OrcaSlicer CLI 集成，可选节点，生成 G-code 打印指令
- **实现 `mesh_scale` 节点**：从 stub 替换为真实均匀缩放实现（简单节点，无需策略模式）
- **废弃 `postprocess_organic_node`**：其 7 步内联逻辑已拆分到独立节点，Phase 2 完成后标记 deprecated
- **废弃 `AutoProvider`**：fail-over 逻辑被 `fallback_chain` 机制替代

## Capabilities

### New Capabilities

- `mesh-format-export`: 网格格式转换基础设施 — `convert_mesh()` 工具函数 + `/api/jobs/{id}/assets/{key}?format=` 导出端点，任意节点产物可按需转换下载
- `boolean-assemble`: manifold3d 布尔装配节点 — 流形校验门 + 布尔运算（flat_bottom/hole/slot 切割），替换 boolean_cuts stub
- `generate-raw-mesh`: 策略化多模型网格生成节点 — 多模型选择（策略层）+ SaaS/本地双部署（配置层），替换 generate_organic_mesh
- `slice-to-gcode`: PrusaSlicer/OrcaSlicer CLI 切片节点 — G-code 生成 + 元数据解析，可选管线节点
- `mesh-scale`: 网格均匀缩放节点 — 替换 mesh_scale stub，目标尺寸缩放 + 底面贴合

### Modified Capabilities

- `langgraph-job-orchestration`: 管线拓扑变更 — 删除 export_formats 节点，新增 slice_to_gcode 节点，generate_organic_mesh 重命名为 generate_raw_mesh

## Impact

- **后端代码**：`backend/graph/nodes/`（5 个节点文件创建/修改/删除）、`backend/graph/strategies/`（新增 generate/boolean 策略）、`backend/graph/configs/`（新增 3 个 config）、`backend/core/mesh_converter.py`（新增）、`backend/api/routes/export.py`（新增）
- **基础设施**：`backend/infra/mesh_providers/`（现有 provider 被策略包装，AutoProvider 删除）
- **测试**：`tests/test_mesh_pipeline.py`（export_formats 测试移除，新增 boolean_assemble/slice_to_gcode/generate_raw_mesh 测试）
- **依赖**：manifold3d（已安装）、PrusaSlicer CLI（外部依赖，`which prusa-slicer` 检测）
- **API**：新增 `/api/jobs/{id}/assets/{key}` 导出端点
- **Legacy 兼容**：`generate_organic_mesh_node` 保留为别名；`postprocess_organic_node` 标记 deprecated
