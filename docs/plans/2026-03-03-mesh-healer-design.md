# mesh_healer 双通道节点设计

> brainstorming 产出。将现有 `mesh_repair` stub 替换为完整的双通道 mesh_healer 节点。
> 这是双通道架构的**模式验证节点**，建立的 pattern 被后续所有业务节点复用。

---

## 背景

- 设计依据：`docs/plans/end-to-end-architecture/2026-03-02-dual-channel-pipeline-design.md` 提案 2
- Phase 0 基础设施已就绪：`NodeStrategy` ABC、`NeuralStrategy` 基类、`execute_with_fallback()`、`fallback_chain`、`AssetStore`
- 现有 `mesh_repair` 节点为 stub（直通转发 raw_mesh）
- 现有 `MeshPostProcessor.repair_mesh()` 使用 PyMeshLab + trimesh 降级（legacy 路径）

---

## 架构决策

### 决策 1：策略组织方式 — 方案 A（单策略多工具管线）

外部暴露 algorithm / neural / auto 三种策略选项，算法策略内部按缺陷严重度编排多工具升级链。用户不感知内部工具选择。

理由：
- 用户心智模型简单（只需选 algorithm/neural/auto）
- 工具互补性强，按严重度升级是最自然的编排方式
- 与双通道架构一致：一个节点 + 两个策略 + fallback_chain

### 决策 2：工具互补关系 — 升级链（非替代）

修复工具按缺陷严重度分级，互补而非替代：
- **trimesh.repair**：normals/winding（轻量，项目已有依赖）
- **PyMeshFix**：holes + non-manifold edges（专用，快速）
- **PyMeshLab**（可选兼容路径）：PyMeshFix 不可用时的替代
- **MeshLib**：self-intersection + voxelization rebuild（重型但彻底）

同一级别内的工具才是替代关系（如 PyMeshFix ↔ PyMeshLab）。

### 决策 3：mesh_scale 保持独立

修复与缩放是不同关注点。mesh_healer 产出 `watertight_mesh`，mesh_scale 消费并产出 `scaled_mesh`。清晰的 requires/produces 链。

### 决策 4：MeshPostProcessor 定位

legacy builder 继续使用 MeshPostProcessor（PyMeshLab 路径）。新管线通过 strategy 直接调用工具链，不经过 MeshPostProcessor。两者共存，互不干扰。

### 决策 5：MeshAnything V2 为可选后处理

retopo 子步骤在修复输出后触发，条件：face_count > retopo_threshold（默认 100k）且 retopo 已启用配置。不影响主修复流程。

---

## 节点注册

```python
@register_node(
    name="mesh_healer",
    display_name="网格修复",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    input_types=["organic"],
    strategies={
        "algorithm": AlgorithmHealStrategy,
        "neural": NeuralHealStrategy,
    },
    default_strategy="algorithm",
    fallback_chain=["algorithm", "neural"],
)
async def mesh_healer_node(ctx: NodeContext) -> None:
    strategy = ctx.get_strategy()
    await strategy.execute(ctx)
```

---

## AlgorithmHealStrategy — 诊断 + 升级链

### 诊断函数

```python
@dataclass
class MeshDiagnosis:
    level: Literal["clean", "mild", "moderate", "severe"]
    issues: list[str]  # 具体问题描述

def diagnose(mesh: trimesh.Trimesh) -> MeshDiagnosis:
    """分析 mesh 缺陷，返回严重度等级。"""
    # clean: is_watertight + is_oriented → 无需修复
    # mild: normals/winding 问题
    # moderate: has_holes or non_manifold edges
    # severe: self_intersection or missing_face_ratio > threshold
```

### 升级链流程

```
输入 mesh → diagnose(mesh)
  │
  ├─ clean → 直通（不修复）
  │
  ├─ mild → Level 1: trimesh.repair
  │    fix_normals() + fix_winding() → 验证 → 通过? → 输出
  │    └─ 未通过 → 升级到 Level 2
  │
  ├─ moderate → Level 2: PyMeshFix (首选) / PyMeshLab (备选)
  │    repair() → 验证 → 通过? → 输出
  │    └─ 未通过 → 升级到 Level 3
  │
  └─ severe → Level 3: MeshLib
       meshToVolume() → gridToMesh() → 验证 → 输出
       └─ 仍失败 → 报错（auto 模式 fallback 到 neural）
```

### 工具可用性

每级工具通过 `try: import` 检测。不可用则跳到下一级。trimesh 是项目基础依赖，永远可用。

### 验证函数

每级修复后统一验证：
```python
def validate_repair(mesh: trimesh.Trimesh) -> bool:
    """检查修复是否成功：is_watertight + volume > 0 + no degenerate faces。"""
```

---

## NeuralHealStrategy — HTTP API

继承 NeuralStrategy 基类，调用模型服务 `/v1/repair`：

```python
class NeuralHealStrategy(NeuralStrategy):
    async def execute(self, ctx: NodeContext) -> None:
        mesh_path = ctx.get_asset("raw_mesh").path
        response = await self._post("/v1/repair", {
            "mesh_uri": mesh_path,
        })
        repaired_path = response["mesh_uri"]
        ctx.put_asset("watertight_mesh", repaired_path, "obj",
                      metadata=response.get("metrics", {}))
```

三态行为（继承自 NeuralStrategy.check_available()）：
- disabled：未配置 endpoint 或 neural_enabled=False
- degraded：endpoint 配置但 health check 失败
- available：endpoint + health OK

适用模型：NKSR (Neural Kernel Surface Reconstruction)，pip 可安装，预训练权重，秒级推理。

---

## MeshAnything V2 Retopo 子步骤

可选后处理，在修复输出后检查：

```
修复输出 mesh → face_count > retopo_threshold?
  ├─ 否 → 直接输出
  └─ 是 → retopo_enabled?
       ├─ 否 → 输出（记录 warning）
       └─ 是 → POST /v1/retopo → 低面数 mesh → 输出
```

Retopo 配置独立于 repair，通过 `pipeline_config.mesh_healer.retopo` 控制。

---

## 配置结构

```yaml
mesh_healer:
  strategy: "auto"           # algorithm / neural / auto
  algorithm:
    retopo_threshold: 100000  # face count 触发 retopo
    voxel_resolution: 128     # MeshLib 体素化分辨率
  neural:
    enabled: false
    endpoint: "http://gpu:8090"
    timeout: 60
  retopo:
    enabled: false
    endpoint: "http://gpu:8091"
    target_faces: 50000
```

---

## 数据流

```
requires: raw_mesh (AssetEntry: path to .glb/.obj)
    ↓
mesh_healer 节点:
  1. ctx.get_asset("raw_mesh") → 加载 mesh (trimesh)
  2. ctx.get_strategy() → AlgorithmHealStrategy / NeuralHealStrategy / auto
  3. strategy.execute(ctx) → 修复/重建
  4. [可选] retopo 子步骤
  5. ctx.put_asset("watertight_mesh", path, format, metadata)
  6. ctx.dispatch_progress() 发送进度事件
    ↓
produces: watertight_mesh (AssetEntry: path + metadata{is_watertight, vertex_count, ...})
```

---

## 文件结构

```
backend/graph/
├── strategies/
│   ├── __init__.py
│   ├── neural.py           # NeuralStrategy 基类（已有）
│   └── heal/
│       ├── __init__.py
│       ├── algorithm.py    # AlgorithmHealStrategy（诊断+升级链）
│       ├── neural.py       # NeuralHealStrategy（HTTP /v1/repair）
│       └── diagnose.py     # MeshDiagnosis + diagnose() + validate_repair()
├── nodes/
│   ├── mesh_repair.py      # 删除（被 mesh_healer.py 替代）
│   └── mesh_healer.py      # 新：双通道节点函数
```

---

## 迁移策略

- `mesh_repair.py` 删除，新建 `mesh_healer.py`
- `@register_node` name 从 `"mesh_repair"` 改为 `"mesh_healer"`
- 下游 `requires=["watertight_mesh"]` 节点不受影响（produces 不变）
- legacy builder 中 `postprocess_organic_node` 不变
- 新 builder discovery 自动注册 mesh_healer
- 测试中 `TestBuilderSwitch` 的 stub 节点列表需更新（mesh_repair → mesh_healer）

---

## 测试策略

| 类别 | 测试内容 |
|------|---------|
| 诊断 | 不同缺陷类型 → 正确分级（clean/mild/moderate/severe） |
| 升级链 | 低级工具失败 → 自动升级到高级 |
| 工具 mock | 每级工具独立测试（mock trimesh/pymeshfix/meshlib） |
| Neural | mock HTTP → 验证请求/响应映射 |
| fallback | algorithm 失败 → auto 模式 fallback 到 neural |
| trace | 复用 TestTraceMerge 模式，验证 fallback_trace 记录 |
| 集成 | 真实 broken mesh 文件跑完整修复链 |
| 配置 | 不同 config 组合（strategy=auto/algorithm/neural, retopo on/off） |

---

## 模式验证意义

此节点建立的 pattern（后续节点直接复用）：
1. **策略文件组织**：`strategies/<domain>/algorithm.py` + `neural.py` + 辅助模块
2. **节点函数简洁**：只调 `ctx.get_strategy()` + `strategy.execute(ctx)`
3. **配置结构**：`strategy` + `algorithm{}` + `neural{}` 三层嵌套
4. **诊断→分级→升级链**：算法策略内部多工具编排的标准模式
5. **Neural HTTP 调用**：继承 NeuralStrategy，只需实现 `execute()`
6. **测试矩阵**：诊断 + 升级链 + fallback + trace 的标准测试结构
