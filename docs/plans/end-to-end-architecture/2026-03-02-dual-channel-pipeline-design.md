# 端到端 3D 打印管线：双通道节点架构设计

> 基于 8 份深度调研文档 + Gemini 跨模型审查 + 现有代码结构分析的综合设计。
> 经 Claude + Codex + Gemini 三方审查修订（2026-03-02），已校准设计与代码现状的一致性。

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

## 零、代码现状基线

> 本节记录设计文档编写时的代码现状，明确哪些是"现有机制"、哪些是"本设计新增"。

### 0.1 现有策略机制

**已有**（无需从零构建）：

- `NodeDescriptor.strategies: dict[str, type[NodeStrategy]]` — 策略注册，值为 `NodeStrategy` 子类引用
- `NodeDescriptor.default_strategy: str | None` — 默认策略名
- `NodeStrategy` ABC — `execute(ctx)` + `check_available()` 两个方法
- `NodeContext.get_strategy()` — 从 `config.strategy` 读取策略名，从 `descriptor.strategies` 实例化并检查可用性
- `BaseNodeConfig.strategy: str = "default"` — 用户通过 `pipeline_config` 选择策略

**策略派发流程（现有）**：
```
节点函数被调用 → _wrap_node() 创建 NodeContext → 节点函数内部调用 ctx.get_strategy()
  → NodeContext 读取 config.strategy → 查找 descriptor.strategies[name] → 实例化 → check_available() → execute()
```

**关键**：策略派发发生在 `NodeContext.get_strategy()` 中，由节点函数自身调用，不在 `_wrap_node()` 中。

### 0.2 现有资产管理

**已有**：

- `AssetEntry` — `key, path, format, producer, metadata` 数据类
- `AssetRegistry` — 内存中的 asset 注册表，`put/get/has/keys/to_dict/from_dict`
- `NodeContext.put_asset(key, path, format, metadata)` / `get_asset(key)` — 节点通过 NodeContext 读写资产
- `PipelineState.assets: Annotated[dict, _merge_dicts]` — 增量合并 reducer

**当前传递方式**：`AssetEntry.path` 存储本地文件路径字符串（如 `/workspace/jobs/{job_id}/mesh.glb`）。

### 0.3 现有占位节点

以下后半段节点目前是 **TODO stub**（仅做直通转发），本设计将用真实实现替换它们：

| 现有名称 | 状态 | 本设计目标名称 |
|---------|------|--------------|
| `mesh_repair` | stub，直接传递 raw_mesh | → `mesh_healer`（MeshLib 算法 + Neural 修复） |
| `mesh_scale` | stub，直接传递 | → 保留或合并到 mesh_healer 后处理 |
| `boolean_cuts` | stub，直接传递 | → `boolean_assemble`（manifold3d + UCSG-NET） |
| `export_formats` | stub，OR 依赖选择最佳 mesh | → `slice_to_gcode`（CuraEngine / OrcaSlicer） |

### 0.4 现有机制（本设计不改变）

- **拦截器（Interceptors）**：`interceptors.py` 提供 `InterceptorRegistry`，legacy builder (`builder.py`) 在 `convert_preview` → `check_printability` 之间动态插入拦截节点。新 builder (`builder_new.py`) 暂无拦截器支持——**Phase 0 必须在 builder 切换前补齐拦截器支持**。
- **HITL（Human-in-the-loop）**：`confirm_with_user` 节点通过 `interrupt_before` 暂停管线，用户通过 `Command(resume=...)` 恢复。此机制与双通道架构正交，继续沿用。
- **SSE 事件**：`_wrap_node()` 在节点执行前后派发 `node.started` / `node.completed` / `node.failed` 事件。`NodeContext.dispatch_progress()` 提供细粒度进度。**新节点必须调用 `ctx.dispatch_progress()` 发送处理进度。**
- **input_type 路由**：`_make_router()` + `_add_routing_edges()` 基于 `input_type` 做条件路由（text/drawing/organic → 不同分析节点）。

---

## 一、架构层

### 1.1 策略派发机制

**在现有 `NodeContext.get_strategy()` 基础上**扩展，增加 auto fallback 能力。

#### 新增字段（需添加到 `NodeDescriptor` 和 `@register_node`）

```python
# NodeDescriptor 新增字段
fallback_chain: list[str] = field(default_factory=list)  # 新增：auto 模式的尝试顺序

# @register_node 示例
@register_node(
    name="mesh_healer",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    strategies={
        "algorithm": MeshLibHealStrategy,      # type[NodeStrategy] 子类引用
        "neural": NeuralPullHealStrategy,       # type[NodeStrategy] 子类引用
    },
    default_strategy="algorithm",
    fallback_chain=["algorithm", "neural"],      # 新增
)
```

#### 扩展 `NodeContext.get_strategy()` 支持 auto 模式

```
ctx.get_strategy() 读取 config.strategy:
  ├─ "algorithm" → 实例化 strategies["algorithm"]，check_available() → execute()
  ├─ "neural"    → 实例化 strategies["neural"]，check_available() → 可用则 execute()，不可用则报错
  └─ "auto"      → 按 descriptor.fallback_chain 顺序尝试：
                     第 1 个策略 check_available() + execute()
                       ├─ 成功 → 返回
                       └─ 失败 → 尝试下一个
                     所有策略均失败 → 报错
```

**关键决策**：fallback 发生在 `NodeContext` 内部，不改变 LangGraph 图结构。图中只有一个 `mesh_healer` 节点，内部多策略派发。

### 1.2 模型服务发现与健康检查

Neural 策略的 `check_available()` 集成服务发现逻辑：

```python
class NeuralStrategyConfig(BaseNodeConfig):
    """扩展 BaseNodeConfig，添加 Neural 通道配置。"""
    neural_enabled: bool = False               # 默认关闭
    neural_endpoint: str | None = None         # http://gpu-server:8090
    neural_timeout: int = 60
    health_check_path: str = "/health"

class NeuralStrategy(NodeStrategy):
    """所有 Neural 策略的基类。"""
    def check_available(self) -> bool:
        """GET {endpoint}/health → 200 则 available。
        继承自 NodeStrategy.check_available()，整合服务发现逻辑。
        """
        if not self.config.neural_enabled or not self.config.neural_endpoint:
            return False
        return self._health_check(self.config.neural_endpoint)
```

**三态设计**（通过 `check_available()` 语义实现）：

| 状态 | 条件 | check_available() | 行为 |
|------|------|-------------------|------|
| disabled（默认） | 未配置 endpoint 或 neural_enabled=False | → False | 不出现在可用策略中 |
| available | endpoint 已配置 + 健康检查通过 | → True | 用户可选择 |
| degraded | endpoint 已配置 + 健康检查失败 | → False | auto 模式跳过 |

### 1.3 数据传递：扩展现有 AssetEntry

**基于现有 `AssetRegistry` / `AssetEntry`**，扩展 `path` 字段的语义：

```python
# 当前用法（保持兼容）
ctx.put_asset("watertight_mesh", path="/workspace/jobs/123/mesh.obj", format="obj")

# 新增：支持 URI 格式（file:/// 或未来 s3://）
ctx.put_asset("watertight_mesh", path="file:///workspace/jobs/123/mesh.obj", format="obj",
              metadata={"vertex_count": 12000, "is_watertight": True})
```

**AssetStore 抽象**（新增，为未来 MinIO 升级预留）：

```python
class AssetStore(Protocol):
    def save(self, job_id: str, name: str, data: bytes, fmt: str) -> str:  # → URI
    def load(self, uri: str) -> bytes:

class LocalAssetStore(AssetStore):    # 试验阶段：file:/// 或本地路径
class MinioAssetStore(AssetStore):    # 未来升级：s3://
```

`AssetStore` 与 `AssetRegistry` 的关系：`AssetStore` 负责持久化（save/load 文件），`AssetRegistry` 负责元数据追踪（key/path/format/producer）。

### 1.4 Builder 统一

- `builder_new.py` 升级为主 builder
- 原 `builder.py` 重命名为 `builder_legacy.py`，标记 deprecated
- `USE_NEW_BUILDER` 默认值改为 `1`

**前置条件（Phase 0 必须完成）**：
- 新 builder 必须支持拦截器机制（移植 `InterceptorRegistry.apply()` 逻辑）
- 所有 `builder.py` 的 SSE 事件、HITL 暂停行为在新 builder 中已覆盖（当前 `_wrap_node()` 已实现）
- 通过完整回归测试后才能切换默认值

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

> **名称说明**：下表使用本设计的目标节点名。现有代码中的占位节点名称映射见「零、代码现状基线 → 0.3」节。

```
节点                    算法策略 (A)                Neural 策略 (N)                 默认
───────────────────────────────────────────────────────────────────────────────────────
generate_cadquery       CadQuery (OCCT)            —                               A
generate_raw_mesh       —                          Hunyuan3D 2.5 Turbo             N
  (现有: generate_organic_mesh)                    SPAR3D
                                                   TRELLIS
                                                   Llama-Mesh
mesh_healer             MeshLib 体素化              Neural-Pull (MIT)               A
  (现有 stub: mesh_repair)                         DeepSDF (MIT)
                                                   MeshAnything V2 (retopo 子步骤)
boolean_assemble        manifold3d                 UCSG-NET (实验)                  A
  (现有 stub: boolean_cuts)
apply_lattice           TPMS 数学函数               —                               A
orientation_optimizer   scipy 差分进化              —                               A
generate_supports       切片引擎自带                GNN 支撑预测 (实验)              A
thermal_simulation      静态几何校验                —                               A
slice_to_gcode          CuraEngine CLI             —                               A
  (现有 stub: export_formats)  OrcaSlicer CLI
```

> **MeshAnything V2** 定位为 `mesh_healer` 内部的 retopo 子步骤（修复后拓扑重建），不单独注册为节点。

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

## 五、实施路线图

> 按提案粒度拆解，每个提案独立走开发流程（brainstorming / OpenSpec → writing-plans → 实现 → 审查）。

### 实施顺序与依赖关系

```
提案 1: 架构骨架（OpenSpec）
    ↓ 完成后，双通道基础设施就绪
提案 2: mesh_healer（brainstorming → OpenSpec）← 双通道模式验证
    ↓ 模式验证后，后续节点复用 pattern
提案 3: boolean_assemble（writing-plans）  ┐
提案 4: slice_to_gcode（brainstorming）    ├ 可并行
提案 5: generate_raw_mesh（brainstorming） ┘
    ↓ Phase 1-2 完成后
提案 6+: Phase 3 节点（逐个评估，多数直接 writing-plans）
```

### 提案 1：架构骨架（Phase 0）

| 属性 | 值 |
|------|---|
| 开发流程 | OpenSpec（改变模块边界 + 接口契约） |
| 阻塞关系 | 阻塞所有后续提案 |
| 预估规模 | 中（~15 个任务） |

**范围**：
- `NodeDescriptor` 新增 `fallback_chain` 字段 + `@register_node` 参数
- `NodeContext.get_strategy()` 扩展 auto 模式（fallback 逻辑）
- `NeuralStrategy` 基类 + `NeuralStrategyConfig`（继承 `BaseNodeConfig`）
- `AssetStore` 抽象 + `LocalAssetStore`（与现有 `AssetRegistry` 集成）
- **拦截器迁移**：`builder_new.py` 补齐 `InterceptorRegistry` 支持
- Builder 统一（SSE + HITL + 拦截器回归测试通过后切换默认值）
- CI 跨平台验证（manifold3d, meshlib wheel）
- **新节点 SSE 契约**：所有新实现节点必须调用 `ctx.dispatch_progress()`

**验收标准**：
- `strategy: "auto"` 在测试节点上可正确 fallback
- `NeuralStrategy.check_available()` 在无 endpoint 时返回 False
- 新 builder 通过所有现有测试（含拦截器、HITL、SSE）

### 提案 2：mesh_healer — 双通道模式验证

| 属性 | 值 |
|------|---|
| 开发流程 | brainstorming → OpenSpec（双通道首个完整示范，模式需验证） |
| 依赖 | 提案 1 完成 |
| 预估规模 | 大（~12 个任务） |

**需要头脑风暴的问题**：
- MeshLib 修复路径选型（体素化 vs 孔洞填充 vs 自相交修复）
- Neural-Pull HTTP API 契约（输入点云还是网格？SDF 重建参数？）
- MeshAnything V2 retopo 子步骤触发条件和参数
- 现有 `mesh_repair` stub → `mesh_healer` 的重命名/迁移策略
- 双通道 auto fallback 的端到端验证方案

**为什么最优先**：这是双通道架构的**模式验证**节点。此处确定的 pattern（策略注册、config 结构、HTTP 调用、check_available、fallback 行为）会被后续所有双通道节点复用。

### 提案 3：boolean_assemble — 布尔装配

| 属性 | 值 |
|------|---|
| 开发流程 | 直接 writing-plans（技术路径明确） |
| 依赖 | 提案 1 完成 |
| 预估规模 | 小（~6 个任务） |

**范围**：
- manifold3d 算法策略（`Manifold.union/subtract/intersect`）
- 流形校验门（`is_manifold_check()` → 通过/体素化修复/报错）
- 现有 `boolean_cuts` stub → `boolean_assemble` 迁移
- 坐标标准化 + 弦差控制（STEP→网格转换参数）

**不需要头脑风暴**：manifold3d Python API 清晰，流形校验+体素化修复流程已在设计文档确定。

### 提案 4：slice_to_gcode — 切片出码

| 属性 | 值 |
|------|---|
| 开发流程 | brainstorming（CLI 集成方案需调研） |
| 依赖 | 提案 1 完成 |
| 预估规模 | 中（~10 个任务） |

**需要头脑风暴的问题**：
- CuraEngine CLI vs OrcaSlicer CLI 命令行接口差异
- 参数映射（layer_height, infill, supports → 各自 CLI 参数格式）
- 临时文件管理 + 进程超时 + 错误处理
- G-code 输出解析 + 打印统计信息提取
- 现有 `export_formats` stub → `slice_to_gcode` 迁移

### 提案 5：generate_raw_mesh — 多模型生成

| 属性 | 值 |
|------|---|
| 开发流程 | brainstorming（多模型 API 差异 + 与现有 organic 流程关系需厘清） |
| 依赖 | 提案 1 完成，提案 2 的双通道 pattern 可参考 |
| 预估规模 | 大（~12 个任务） |

**需要头脑风暴的问题**：
- 4 种模型（Hunyuan3D 2.5、SPAR3D、TRELLIS、Llama-Mesh）API 差异
- 坐标标准化实现（Y-up → Z-up、归一化 → mm）
- 与现有 `generate_organic_mesh`（已有 Tripo3D/Hunyuan3D provider）的关系：重构还是新建？
- 多模型选择策略（用户手选 vs 自动推荐）

### 提案 6+：Phase 3 节点（后期逐个评估）

以下节点在提案 1-5 完成后逐个启动，多数技术明确，直接 writing-plans：

| 节点 | 流程 | 说明 |
|------|------|------|
| `apply_lattice` | writing-plans | TPMS 数学函数，算法明确 |
| `orientation_optimizer` | writing-plans | scipy 差分进化，优化目标明确 |
| `thermal_simulation` | writing-plans | 静态几何校验，规则明确 |
| `generate_supports` | writing-plans | 委托切片引擎，接口简单 |
| UCSG-NET Neural 通道 | brainstorming | 实验性布尔 Neural 策略 |
| GNN 支撑预测 | brainstorming | 实验性 Neural 策略 |

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
| 策略派发位置 | NodeContext.get_strategy()（现有） | 节点自主调用，保持节点对策略的控制权 |
| 资产管理 | 扩展现有 AssetRegistry + 新增 AssetStore | AssetRegistry 管元数据，AssetStore 管持久化 |
| API 契约 | 按能力分类 | 不同模型输入输出差异太大，无法完全统一 |
| 数据传递 | 本地文件 URI（兼容现有 path 字段） | 试验阶段足够，后续升级 MinIO 只需改 URI scheme |
| 切片引擎 | CuraEngine + OrcaSlicer 双选 | 双通道理念，用户自选 |
| 实施优先 | 架构骨架 → 打通闭环 → Neural 扩展 → 补全 | 先有可演示的完整链路 |
| 拦截器迁移 | Phase 0 前置完成 | builder 切换前必须保证拦截器正常工作 |
| retopo 定位 | mesh_healer 子步骤（非独立节点） | MeshAnything V2 是修复后拓扑重建，逻辑紧耦合 |
| 授权策略 | 权重可下载即可用 | 试验阶段，暂无商业计划 |
| SOTA 更新 | Hunyuan3D 2.5 Turbo, TRELLIS 纳入 | Gemini 搜索确认的最新进展 |

---

## 附录：审查修订记录

> 2026-03-02 三方审查（Claude + Codex + Gemini）后修订。

| # | 问题 | 严重度 | 处置 |
|---|------|--------|------|
| F1 | 策略派发位置描述为 `_wrap_node()` 内部，实际在 `NodeContext.get_strategy()` | P1 | 修复：重写 §1.1，添加 §0.1 现状基线 |
| F2 | `fallback_chain` 描述为现有机制，实为新增字段 | P1 | 修复：明确标注为"新增" |
| F3 | strategies 值类型写成函数引用，应为 `type[NodeStrategy]` 子类引用 | P1 | 修复：示例改用 `MeshLibHealStrategy` 类名 |
| F4 | 未提及现有 AssetRegistry/AssetEntry，提议全新 AssetStore | P1 | 修复：基于现有 AssetRegistry 扩展，AssetStore 定位为持久化层 |
| F5 | 节点命名与代码不一致（mesh_healer vs mesh_repair） | P1 | 修复：添加 §0.3 名称映射表 |
| F6 | Builder 切换未考虑拦截器迁移 | P1 | 修复：§1.4 增加前置条件，Phase 0 增加拦截器迁移 |
| F7 | 占位节点现状未说明 | P1 | 修复：添加 §0.3 占位节点说明 |
| F8 | HITL 语义未涉及 | P2 | 添加 §0.4 现有机制说明 |
| F9 | SSE 细粒度进度未要求 | P2 | 修复：§0.4 + Phase 0 添加 SSE 契约 |
| F10 | ServiceDiscovery 与 check_available() 重复 | P2 | 修复：§1.2 整合为 NeuralStrategy 基类 |
| F11 | retopo 能力未映射到节点 | P2 | 修复：明确为 mesh_healer 子步骤 |
