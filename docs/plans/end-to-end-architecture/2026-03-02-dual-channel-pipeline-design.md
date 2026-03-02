# 端到端 3D 打印管线：双通道节点架构设计

> 基于 8 份深度调研文档 + Gemini 跨模型审查 + 现有代码结构分析的综合设计。

---

## 设计原则

| 原则 | 说明 |
|------|------|
| 混合架构 | AI 模型做"生坯创造"，确定性算法做"精密手术" |
| 策略内置 | 每个逻辑节点注册一次，内部通过 strategies 切换算法/Neural |
| 消费不部署 | 主管线只通过 HTTP API 消费模型，不负责模型部署和加载 |
| Neural 默认禁用 | 依赖自部署模型的策略默认关闭，用户配置 endpoint 后激活 |
| 权重可下载即可用 | 试验阶段无商业计划，不受授权限制 |
| 用户握选择权 | algorithm/neural/auto 三种策略，可插拔，用户自选 |

---

## 一、架构层

### 1.1 策略派发机制

扩展现有 `@register_node` 的 `strategies` 参数，增加 auto fallback：

```python
@register_node(
    name="mesh_healer",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    strategies={
        "algorithm": meshlib_heal_strategy,
        "neural": neural_pull_heal_strategy,
    },
    default_strategy="algorithm",
    fallback_chain=["algorithm", "neural"],  # auto 模式的尝试顺序
)
```

**派发逻辑**（在 `_wrap_node()` 内部）：

```
读取 pipeline_config[node_name]["strategy"]
  ├─ "algorithm" → 直接调用算法策略
  ├─ "neural"    → 检查 endpoint 可用性 → 可用则调用，不可用则报错
  └─ "auto"      → 按 fallback_chain 顺序尝试
                     algorithm 成功 → 返回
                     algorithm 失败 → 检查 neural endpoint
                       ├─ 可用 → 尝试 neural
                       └─ 不可用 → 报失败
```

**关键决策**：fallback 发生在节点内部，不改变 LangGraph 图结构。图中只有一个 `mesh_healer` 节点，内部多策略派发。

### 1.2 模型服务发现与健康检查

```python
class NeuralStrategyConfig(BaseModel):
    enabled: bool = False                    # 默认关闭
    endpoint: str | None = None              # http://gpu-server:8090
    timeout: int = 60
    health_check_path: str = "/health"

class ServiceDiscovery:
    def check_availability(self, config: NeuralStrategyConfig) -> bool:
        """GET {endpoint}/health → 200 则 available"""

    def get_available_strategies(self, node_name: str) -> list[str]:
        """返回当前可用的策略列表（algorithm 始终可用）"""
```

**三态设计**：

| 状态 | 条件 | 行为 |
|------|------|------|
| disabled（默认） | 未配置 endpoint | 不出现在可用策略中 |
| available | endpoint 已配置 + 健康检查通过 | 用户可选择 |
| degraded | endpoint 已配置 + 健康检查失败 | auto 模式跳过 |

### 1.3 数据传递：本地文件 URI

节点间通过 `PipelineState.assets` 传递文件 URI（非 Base64）：

```python
# 节点产出
return {
    "assets": {
        "watertight_mesh": {
            "uri": f"file:///workspace/jobs/{job_id}/watertight.obj",
            "format": "obj",
            "vertex_count": 12000,
        }
    }
}
```

**AssetStore 抽象**：

```python
class AssetStore(Protocol):
    def save(self, job_id: str, name: str, data: bytes, fmt: str) -> str:
    def load(self, uri: str) -> bytes:

class LocalAssetStore(AssetStore):    # 试验阶段：file:///
class MinioAssetStore(AssetStore):    # 未来升级：s3://
```

### 1.4 Builder 统一

- `builder_new.py` 升级为主 builder
- 原 `builder.py` 重命名为 `builder_legacy.py`，标记 deprecated
- `USE_NEW_BUILDER` 默认值改为 `1`

---

## 二、数据层

### 2.1 坐标系/单位标准化

Neural 策略输出后强制标准化（作为策略内置后处理）：

```
Neural 模型输出 → normalize_mesh()
  ├─ 坐标系: Y-up → Z-up（旋转 -90° around X）
  ├─ 单位: 归一化 [-1,1] → mm（按用户指定目标尺寸缩放）
  ├─ 底面贴合: PCA 主轴分析 → 最大平面贴 Z=0
  └─ 输出: 标准化 OBJ + 元数据 (bbox_mm, volume_mm3)
```

算法通道（CadQuery）天然 mm + Z-up，无需标准化。

### 2.2 STEP→网格弦差控制

```python
class StepToMeshConfig(BaseModel):
    linear_deflection: float = 0.01    # mm
    angular_deflection: float = 0.5    # degrees

    @classmethod
    def high_precision(cls):
        """精密机械件"""
        return cls(linear_deflection=0.005, angular_deflection=0.1)

    @classmethod
    def standard(cls):
        """普通零件"""
        return cls(linear_deflection=0.01, angular_deflection=0.5)
```

通过 `pipeline_config["step_to_mesh"]` 暴露给用户。

### 2.3 布尔运算前流形校验门

`boolean_assemble` 内置前处理：

```
输入网格 → is_manifold_check()
  ├─ 通过 → 直接送 manifold3d
  └─ 未通过 → force_voxelize()（MeshLib 体素化重采样）
                └─ 再次 is_manifold_check()
                     ├─ 通过 → 送 manifold3d
                     └─ 未通过 → 报错
```

---

## 三、节点层

### 3.1 双通道映射表

```
节点                    算法策略 (A)                Neural 策略 (N)                 默认
───────────────────────────────────────────────────────────────────────────────────────
generate_cadquery       CadQuery (OCCT)            —                               A
generate_raw_mesh       —                          Hunyuan3D 2.5 Turbo             N
                                                   SPAR3D
                                                   TRELLIS
                                                   Llama-Mesh
mesh_healer             MeshLib 体素化              Neural-Pull (MIT)               A
                                                   DeepSDF (MIT)
                                                   MeshAnything V2
boolean_assemble        manifold3d                 UCSG-NET (实验)                  A
apply_lattice           TPMS 数学函数               —                               A
orientation_optimizer   scipy 差分进化              —                               A
generate_supports       切片引擎自带                GNN 支撑预测 (实验)              A
thermal_simulation      静态几何校验                —                               A
slice_to_gcode          CuraEngine CLI             —                               A
                        OrcaSlicer CLI
```

### 3.2 模型服务 API 契约

按能力（capability）分类，共 4 种：

**Capability: generate**
```
POST /v1/generate
Request:  { prompt: str, image_uri?: str, quality?: str }
Response: { mesh_uri: str, metadata: { vertices, faces, format } }
适用: Hunyuan3D 2.5, SPAR3D, TRELLIS, Llama-Mesh
```

**Capability: repair**
```
POST /v1/repair
Request:  { mesh_uri: str }
Response: { mesh_uri: str, metrics: { is_watertight, holes_filled } }
适用: Neural-Pull, DeepSDF
```

**Capability: retopo**
```
POST /v1/retopo
Request:  { mesh_uri: str, target_faces?: int }
Response: { mesh_uri: str, metrics: { face_count, quad_ratio } }
适用: MeshAnything V2
```

**Capability: boolean（实验）**
```
POST /v1/boolean
Request:  { mesh_a_uri: str, mesh_b_uri: str, op: "union"|"subtract"|"intersect" }
Response: { mesh_uri: str }
适用: UCSG-NET
```

**共享接口**
```
GET /health → { status: "ok", model: str, gpu_memory_used: int }
GET /info   → { model_name, version, capabilities: list[str] }
```

模型服务与主管线共享文件系统（试验阶段挂载同一 workspace 目录）。

---

## 四、工程层

### 4.1 C++ 绑定跨平台验证

| 依赖 | PyPI wheel | macOS ARM | Linux x86_64 |
|------|-----------|-----------|--------------|
| manifold3d | 有 | 有 | 有 |
| meshlib | 有 | 有 | 有 |
| cadquery | 需特殊安装 | 保持现有 uv 方式 | 保持现有 uv 方式 |

CI 矩阵增加双平台 `uv sync` 测试。安装失败的 C++ 包，对应算法策略标记 unavailable。

### 4.2 用户视角的使用流程

```
步骤 1：安装 CADPilot（uv sync）
        → 所有算法策略立即可用
        → 所有 Neural 策略默认禁用

步骤 2（可选）：部署模型服务
        → docker run -p 8090:8090 cadpilot/neural-pull-server
        → 或自行 FastAPI + PyTorch 包装

步骤 3：配置 endpoint
        → pipeline_config.yaml:
            mesh_healer:
              strategy: "auto"
              neural:
                enabled: true
                endpoint: "http://192.168.1.100:8090"

步骤 4：运行管线
        → strategy: "auto"      → 算法优先，失败 fallback Neural
        → strategy: "neural"    → 强制 Neural（未部署则报错）
        → strategy: "algorithm" → 纯算法
```

---

## 五、实施优先级

### Phase 0 — 架构骨架

- 策略派发机制扩展（fallback_chain + auto 模式）
- ServiceDiscovery + NeuralStrategyConfig
- AssetStore 抽象 + LocalAssetStore
- Builder 统一（Legacy → deprecated）
- CI 跨平台验证

### Phase 1 — 高成功率节点 + 打通闭环

- `boolean_assemble`: manifold3d 算法策略（成功率 95%）
- `slice_to_gcode`: CuraEngine + OrcaSlicer 双选项（成功率 99%）
- 坐标标准化 + 弦差控制 + 流形校验门
- 演示：CadQuery 零件 + 有机体 → 布尔装配 → G-code

### Phase 2 — 生成源扩展 + Neural 通道预埋

- `generate_raw_mesh`: Hunyuan3D 2.5 / SPAR3D / TRELLIS
- `mesh_healer`: MeshLib 算法 + Neural-Pull Neural 策略
- MeshAnything V2 retopo 子步骤
- 对比评估框架（同一输入双通道，输出质量指标）

### Phase 3 — 补全与优化

- `apply_lattice`: TPMS 数学点阵
- `orientation_optimizer`: scipy 差分进化
- `thermal_simulation`: 静态几何校验
- `generate_supports`: 委托切片引擎
- 实验性 Neural 通道: UCSG-NET, GNN Slicer

---

## 技术栈武器库（汇总）

| 职责 | 算法通道 | Neural 通道 |
|------|----------|------------|
| 机械建模 | CadQuery (OCCT) | — |
| 艺术生成 | — | Hunyuan3D 2.5 Turbo / SPAR3D / TRELLIS / Llama-Mesh |
| 拓扑重建 | MeshLib | MeshAnything V2 |
| 网格修复 | MeshLib（体素化） | Neural-Pull / DeepSDF |
| 布尔运算 | manifold3d | UCSG-NET（实验） |
| 摆放寻优 | scipy 差分进化 | — |
| 点阵优化 | TPMS (skimage) | — |
| 切片出码 | CuraEngine / OrcaSlicer CLI | — |

---

## 附录：关键决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Builder 基线 | New builder (builder_new.py) | PipelineState 的 assets/data 天然支持异构中间产物 |
| 双通道建模 | 策略内置（方案 A） | 图节点数不膨胀，复用现有 strategies 机制 |
| API 契约 | 按能力分类 | 不同模型输入输出差异太大，无法完全统一 |
| 数据传递 | 本地文件 URI | 试验阶段足够，后续升级 MinIO 只需改 URI scheme |
| 切片引擎 | CuraEngine + OrcaSlicer 双选 | 双通道理念，用户自选 |
| 实施优先 | 架构骨架 → 打通闭环 → Neural 扩展 → 补全 | 先有可演示的完整链路 |
| 授权策略 | 权重可下载即可用 | 试验阶段，暂无商业计划 |
| SOTA 更新 | Hunyuan3D 2.5 Turbo, TRELLIS 纳入 | Gemini 搜索确认的最新进展 |
