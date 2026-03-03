## 1. 诊断模块

- [ ] 1.1 创建 `backend/graph/strategies/heal/__init__.py` 和 `diagnose.py`，实现 `MeshDiagnosis` 数据类和 `diagnose(mesh)` 函数（分级：clean/mild/moderate/severe）
- [ ] 1.2 实现 `validate_repair(mesh)` 函数（is_watertight + volume > 0 + 无退化面）
- [ ] 1.3 编写诊断模块单元测试：构造不同缺陷类型的 mesh → 验证正确分级

## 2. AlgorithmHealStrategy

- [ ] 2.1 创建 `backend/graph/strategies/heal/algorithm.py`，实现 AlgorithmHealStrategy 类（继承 NodeStrategy）
- [ ] 2.2 实现 Level 1 修复：trimesh.repair（fix_normals + fix_winding + fill_holes）
- [ ] 2.3 实现 Level 2 修复：PyMeshFix 首选 / PyMeshLab 备选，含 try-import 可用性检测
- [ ] 2.4 实现 Level 3 修复：MeshLib 体素化重建（meshToVolume → gridToMesh），含 try-import 可用性检测
- [ ] 2.5 实现升级链编排：diagnose → 选择起始级别 → 执行 → validate → 通过/升级 → 循环
- [ ] 2.6 编写 AlgorithmHealStrategy 单元测试：mock 各级工具，验证升级链行为和工具不可用时的跳级

## 3. NeuralHealStrategy

- [ ] 3.1 创建 `backend/graph/strategies/heal/neural.py`，实现 NeuralHealStrategy（继承 NeuralStrategy），调用 `/v1/repair` HTTP 端点
- [ ] 3.2 编写 NeuralHealStrategy 单元测试：mock HTTP 响应，验证请求/响应映射和三态行为

## 4. 节点实现

- [ ] 4.1 删除 `backend/graph/nodes/mesh_repair.py`，创建 `mesh_healer.py`，注册 `mesh_healer` 节点（strategies + fallback_chain + dispatch_progress）
- [ ] 4.2 实现可选 retopo 子步骤逻辑（face_count > threshold 且 retopo.enabled 时调用 `/v1/retopo`）
- [ ] 4.3 添加 `pymeshfix` 到项目依赖（`uv add pymeshfix`）

## 5. 配置与迁移

- [ ] 5.1 定义 MeshHealerConfig（strategy + algorithm{voxel_resolution, retopo_threshold} + neural{enabled, endpoint, timeout} + retopo{enabled, endpoint, target_faces}）
- [ ] 5.2 更新 `test_graph_builder.py` 中 TestBuilderSwitch：stub 节点列表 mesh_repair → mesh_healer
- [ ] 5.3 更新 node discovery：确认 mesh_healer 被自动发现注册

## 6. 集成测试与验证

- [ ] 6.1 编写 fallback 集成测试：algorithm 失败 → auto 模式 fallback 到 neural（mock HTTP）
- [ ] 6.2 编写 fallback_trace 测试：验证 node_trace 中 fallback 字段记录正确
- [ ] 6.3 运行完整测试套件，确认无回归
