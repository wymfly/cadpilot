## Why

现有 `mesh_repair` 节点为 stub（直通转发 raw_mesh），有机体管线无法生产可 3D 打印的水密网格。mesh_healer 是双通道架构的**模式验证节点**——此处确定的 pattern（策略注册、config 结构、诊断升级链、HTTP 调用、fallback 行为）将被后续所有双通道节点复用。Phase 0 基础设施已就绪，现在是实现首个完整业务节点的时机。

## What Changes

- 删除 `mesh_repair` stub，替换为完整的 `mesh_healer` 双通道节点
- 新增 `AlgorithmHealStrategy`：按缺陷严重度编排多工具升级链（trimesh → PyMeshFix → MeshLib）
- 新增 `NeuralHealStrategy`：继承 NeuralStrategy 基类，通过 HTTP `/v1/repair` 调用 NKSR 模型服务
- 新增 `MeshDiagnosis` 诊断模块：分析 mesh 缺陷类型，决定修复级别
- 新增可选 MeshAnything V2 retopo 子步骤（修复后拓扑重建，高面数时触发）
- 新增 `mesh_healer` 配置结构（strategy + algorithm{} + neural{} + retopo{}）
- 建立双通道节点的标准开发模式（文件组织、测试矩阵、配置约定）

## Capabilities

### New Capabilities

- `mesh-healing`: 网格修复能力——诊断 mesh 缺陷类型，按严重度选择修复工具链，支持 algorithm/neural/auto 三种策略模式，产出水密网格
- `mesh-diagnosis`: 网格诊断能力——分析 mesh 拓扑缺陷（normals、holes、non-manifold、self-intersection），输出缺陷分级和问题清单

### Modified Capabilities

- `langgraph-job-orchestration`: mesh_repair 节点重命名为 mesh_healer，图拓扑中节点名变更

## Impact

- **代码**：`backend/graph/nodes/mesh_repair.py` 删除，新增 `mesh_healer.py` + `backend/graph/strategies/heal/` 模块
- **依赖**：新增 `pymeshfix`（PyPI wheel）；`meshlib` 已在 Phase 0 验证
- **API**：Neural 策略依赖外部模型服务 `/v1/repair` 端点（默认禁用）
- **测试**：`test_graph_builder.py` 中 `TestBuilderSwitch` 的 stub 节点列表需更新
- **配置**：`pipeline_config` 新增 `mesh_healer` 配置节
