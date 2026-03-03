## Context

Phase 0 基础设施已就绪（`NodeStrategy` ABC、`NeuralStrategy` 基类、`execute_with_fallback()`、`fallback_chain`、`AssetStore`），现需实现首个完整双通道业务节点。

当前状态：
- `mesh_repair` 节点为 stub（直通转发 raw_mesh，不做修复）
- `MeshPostProcessor.repair_mesh()` 使用 PyMeshLab + trimesh 降级（legacy 路径）
- 技术验证（2026-03-03）确认：MeshLib 体素化修复 < 0.3% 体积误差、PyMeshFix pip 可安装、NKSR 预训练秒级推理

详细设计见 brainstorming 产出：`docs/plans/2026-03-03-mesh-healer-design.md`

## Goals / Non-Goals

**Goals:**
- 实现可生产水密网格的 mesh_healer 节点，替代 stub
- 建立双通道节点的标准开发模式（后续节点直接复用 pattern）
- algorithm 策略：按缺陷严重度编排多工具升级链
- neural 策略：通过 HTTP API 调用 NKSR 模型服务（默认禁用）
- auto 模式：algorithm 优先，失败 fallback 到 neural

**Non-Goals:**
- 不部署 NKSR 模型服务（只实现客户端调用）
- 不重构 MeshPostProcessor（legacy builder 继续使用）
- 不实现 mesh_scale（保持独立节点，后续提案处理）
- 不实现 MeshAnything V2 retopo 的模型服务端（只预留配置和调用接口）

## Decisions

### D1: 策略组织 — 单策略多工具管线（方案 A）

**选择**：一个 AlgorithmHealStrategy 内部编排多工具升级链

**替代方案**：
- 方案 B（多策略平铺）：每个工具注册为独立策略 → 用户需了解工具差异，心智负担重
- 方案 C（策略组合器）：引入策略编排器新抽象 → 过度工程

**理由**：工具按缺陷严重度互补（trimesh→PyMeshFix→MeshLib），升级链是最自然的编排方式。用户只需选 algorithm/neural/auto。

### D2: 工具升级链顺序

```
Level 1: trimesh.repair（轻量，项目已有依赖）— normals/winding
Level 2: PyMeshFix（首选）/ PyMeshLab（备选）— holes/non-manifold
Level 3: MeshLib 体素化（重型但彻底）— self-intersection/大面积缺失
```

**理由**：从轻到重，能用轻量工具解决的不必动用重型工具。同级工具为替代关系（PyMeshFix ↔ PyMeshLab），跨级工具为升级关系。

### D3: 诊断驱动 vs 盲修复

**选择**：先诊断缺陷类型，再选择对应级别工具

**替代方案**：不诊断，直接跑完整升级链 → 浪费时间（多数 mesh 只需 Level 1）

**理由**：诊断成本极低（trimesh 属性检查），但能跳过不必要的重修复步骤。

### D4: MeshPostProcessor 共存策略

**选择**：legacy builder 继续使用 MeshPostProcessor，新管线用 strategy 直接调用

**理由**：避免一次性大重构。两者共存期间，legacy 路径可随时验证结果一致性。

### D5: 文件组织 — strategies/{domain}/ 模式

**选择**：`backend/graph/strategies/heal/` 目录下 algorithm.py + neural.py + diagnose.py

**理由**：按业务域组织策略文件，后续节点（如 `strategies/boolean/`、`strategies/slice/`）复用同一模式。

## Risks / Trade-offs

- **[MeshLib API 文档稀疏]** → 技术验证已确认核心 API 可用；缺少文档的功能不使用
- **[PyMeshFix 可能不支持所有平台]** → PyMeshLab 作为同级备选；最差情况直接升级到 Level 3
- **[诊断误判导致选错修复级别]** → 每级修复后有验证步骤，失败自动升级；最终兜底是 MeshLib 体素化
- **[Neural 策略无法验证（无 NKSR 服务）]** → 通过 mock HTTP 测试客户端逻辑；neural_enabled 默认 false，不影响主路径
- **[mesh_repair → mesh_healer 重命名]** → 下游节点通过 requires/produces 关联（`watertight_mesh`），不依赖节点名；TestBuilderSwitch 需更新
