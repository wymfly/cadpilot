# 插件式管线架构设计

> **目标**: 将 CADPilot 的 LangGraph 管线重构为完全可插拔的节点体系，支持声明式依赖、多策略选择、精细化参数配置，使新增节点的成本降至"一个文件 + 一个装饰器"。

---

## 1. 设计约束与决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 执行引擎 | 保留 LangGraph StateGraph | checkpoint / HITL / SSE 事件等基础设施已验证，不值得重写 |
| 执行拓扑 | 声明式依赖图（requires/produces） | 节点声明输入输出 asset，系统自动推导拓扑排序 |
| 策略选择 | 节点配置内 strategy 字段 | 每个节点的 config model 含 strategy 枚举，节点内部分发到不同实现 |
| 架构范围 | 全管线统一（前半程+后半程） | 分析/生成节点也纳入注册体系，支持策略切换和参数配置 |
| 数据传递 | AssetRegistry + NodeContext | 替代 25+ 个散装字段，节点只跟 NodeContext 打交道 |
| 依赖不满足 | 报错而非自动拉起 | 避免意外开销（如自动拉起付费 API 节点） |

---

## 2. 核心抽象层

### 2.1 NodeDescriptor — 节点声明

每个节点通过 `@register_node` 装饰器注册，声明完整的元数据：

```python
@register_node(
    name="orientation_optimizer",
    display_name="最佳摆放寻优",

    # ── 依赖声明 ──
    requires=["watertight_mesh"],       # 需要的 asset keys
    produces=["oriented_mesh"],         # 产出的 asset keys

    # ── 适用性 ──
    input_types=["text", "drawing", "organic"],

    # ── 配置 ──
    config_model=OrientationConfig,

    # ── 策略 ──
    strategies={
        "scipy": ScipyOrientationStrategy,
        "genetic": GeneticOrientationStrategy,
    },
    default_strategy="scipy",

    # ── 行为标记 ──
    is_entry=False,
    supports_hitl=False,
    non_fatal=True,
)
async def orientation_optimizer(ctx: NodeContext) -> NodeResult:
    strategy = ctx.get_strategy()
    mesh = ctx.get_asset("watertight_mesh")
    result = await strategy.execute(mesh, ctx.config)
    ctx.put_asset("oriented_mesh", result.path, format="stl")
    return NodeResult(reasoning={"method": ctx.config.strategy})
```

### 2.2 NodeStrategy — 策略接口

```python
class NodeStrategy(ABC):
    """单个节点的一种实现方案。"""

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        """执行策略逻辑。参数由节点函数自行传入。"""
        ...

    def check_available(self) -> bool:
        """检测该策略的依赖是否可用（如 pymeshlab 是否安装）。"""
        return True
```

策略是独立的类，不感知管线，只做具体计算。节点函数通过 `ctx.get_strategy()` 获取当前选中的策略实例。

### 2.3 节点配置模型

每个节点定义自己的 Pydantic 配置模型，`enabled` 和 `strategy` 是标准字段：

```python
class OrientationConfig(BaseNodeConfig):
    """摆放寻优节点配置"""
    strategy: str = "scipy"

    # 通用参数
    weight_height: float = 0.4
    weight_overhang: float = 0.4
    weight_support: float = 0.2

    # scipy 专属
    max_iterations: int = 100

    # genetic 专属
    population_size: int = 50
    generations: int = 20

class BaseNodeConfig(BaseModel):
    """所有节点配置的基类"""
    enabled: bool = True
```

### 2.4 NodeContext — 节点执行上下文

```python
class NodeContext:
    """节点运行时上下文 — LangGraph State 的视图层。"""

    job_id: str
    input_type: str

    # ── Asset 操作 ──
    def get_asset(self, key: str) -> AssetEntry: ...
    def put_asset(self, key: str, path: str | Path, format: str,
                  metadata: dict | None = None): ...
    def has_asset(self, key: str) -> bool: ...

    # ── 语义数据 ──
    def get_data(self, key: str) -> Any: ...
    def put_data(self, key: str, value: Any): ...

    # ── 配置 & 策略 ──
    config: BaseModel
    def get_strategy(self) -> NodeStrategy: ...

    # ── 事件分发 ──
    async def dispatch(self, event: str, payload: dict): ...
    async def dispatch_progress(self, step: str, progress: float, message: str = ""): ...
```

`NodeContext` 是 `PipelineState` 的**视图层**，节点完全不感知 LangGraph State 结构。

### 2.5 AssetEntry — 资产条目

```python
@dataclass
class AssetEntry:
    key: str                # "step_model"
    path: str               # "outputs/{job_id}/model.step"
    format: str             # "step"
    producer: str           # "generate_step_text"
    metadata: dict | None   # 额外元数据
```

---

## 3. 注册表与依赖解析

### 3.1 NodeRegistry

```python
class NodeRegistry:
    _nodes: dict[str, NodeDescriptor] = {}

    def register(self, descriptor: NodeDescriptor): ...
    def get(self, name: str) -> NodeDescriptor: ...
    def all(self) -> list[NodeDescriptor]: ...
    def find_producers(self, asset_key: str) -> list[NodeDescriptor]: ...
    def find_consumers(self, asset_key: str) -> list[NodeDescriptor]: ...

registry = NodeRegistry()  # 模块级单例
```

节点模块被 import 时，装饰器自动调用 `registry.register()`。`discover_nodes()` 扫描 `backend/graph/nodes/` 确保所有模块被加载。

### 3.2 DependencyResolver

```python
class DependencyResolver:
    def resolve(
        self,
        registry: NodeRegistry,
        enabled_nodes: set[str],
        input_type: str,
    ) -> ResolvedPipeline:
        """
        1. 过滤：只保留 enabled 且 input_type 匹配的节点
        2. 依赖检查：requires 的 asset 必须有 producer（未满足→报错）
        3. 冲突检测：同一 asset 不允许多个 producer
        4. 拓扑排序：基于 requires/produces DAG，Kahn 算法
        """
```

**关键决策**：依赖不满足时**报错**，而非自动拉起上游节点。原因：
- 避免意外开销（如自动拉起付费 API 节点）
- 报错信息明确告知用户缺少哪个节点

### 3.3 ResolvedPipeline

```python
@dataclass
class ResolvedPipeline:
    ordered_nodes: list[NodeDescriptor]     # 拓扑排序后的有序列表
    edges: dict[str, list[str]]             # {node: [predecessors]}
    asset_producers: dict[str, str]         # {asset_key: producer_node}
    interrupt_before: list[str]             # HITL 中断点
    def validate(self) -> list[str]: ...    # 校验无环、依赖满足、无冲突
```

### 3.4 OR 依赖语法

```python
# AND: requires=["a", "b"]         → 需要 a 且 b
# OR:  requires=[["a", "b"]]       → 需要 a 或 b
# 混合: requires=["c", ["a", "b"]] → 需要 c 且 (a 或 b)

@register_node(
    name="check_printability",
    requires=[["step_model", "watertight_mesh"]],  # OR
    produces=["printability_report"],
)
```

OR 组只要有一个 asset 的 producer 存在即满足。

### 3.5 同一 Asset 多生产者

基于 `input_types` 过滤后，同一 asset 在某次执行中只有一个生产者：

```python
@register_node(name="generate_step_text", input_types=["text"],
               produces=["step_model", "generated_code"])
@register_node(name="generate_step_drawing", input_types=["drawing"],
               produces=["step_model", "generated_code"])
```

`input_type="text"` 时只有 `generate_step_text` 激活，不冲突。过滤后仍有多个 → 报错。

---

## 4. PipelineBuilder 与 State 适配

### 4.1 PipelineBuilder

```python
class PipelineBuilder:
    def build(self, resolved: ResolvedPipeline) -> StateGraph:
        workflow = StateGraph(PipelineState)

        for desc in resolved.ordered_nodes:
            wrapped = self._wrap_node(desc)
            workflow.add_node(desc.name, wrapped)

        self._wire_edges(workflow, resolved)
        return workflow

    def _wrap_node(self, desc: NodeDescriptor) -> Callable:
        """将 async def node(ctx: NodeContext) 包装为 LangGraph 兼容签名。"""
        async def wrapper(state: PipelineState) -> dict:
            ctx = NodeContext.from_state(state, desc)
            result = await desc.fn(ctx)
            return ctx.to_state_diff()
        return timed_node(desc.name)(wrapper)
```

### 4.2 PipelineState（新 LangGraph State）

```python
class PipelineState(TypedDict, total=False):
    job_id: str
    input_type: str

    # 节点间传递文件产物的唯一通道
    assets: dict[str, dict]         # {"step_model": {"path": "...", "format": "step"}}

    # 节点间传递结构化数据的唯一通道
    data: dict[str, Any]            # {"intent_spec": {...}, "drawing_spec": {...}}

    # 管线配置
    pipeline_config: dict[str, dict]

    # 生命周期
    status: str
    error: str | None
    failure_reason: str | None

    # 执行追踪（append-only）
    node_trace: Annotated[list[dict], operator.add]
```

### 4.3 NodeContext ↔ PipelineState 映射

```python
class NodeContext:
    @classmethod
    def from_state(cls, state: PipelineState, desc: NodeDescriptor) -> NodeContext:
        assets = AssetRegistry.from_dict(state.get("assets") or {})
        raw_config = (state.get("pipeline_config") or {}).get(desc.name, {})
        config = desc.config_model(**raw_config)
        strategy_cls = desc.strategies[config.strategy]
        strategy = strategy_cls()
        return cls(job_id=state["job_id"], input_type=state["input_type"],
                   assets=assets, data=dict(state.get("data") or {}),
                   config=config, strategy=strategy, _descriptor=desc)

    def to_state_diff(self) -> dict:
        diff = {}
        if self._assets_dirty:
            diff["assets"] = self.assets.to_dict()
        if self._data_dirty:
            diff["data"] = self.data
        diff["node_trace"] = [self._build_trace_entry()]
        return diff
```

### 4.4 图编译入口

```python
async def get_compiled_graph(pipeline_config: dict | None = None, input_type: str = "text"):
    config = parse_pipeline_config(pipeline_config)
    enabled = {name for name, cfg in config.items() if cfg.get("enabled", True)}
    resolved = DependencyResolver().resolve(registry, enabled, input_type)
    workflow = PipelineBuilder().build(resolved)
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=resolved.interrupt_before,
    )
```

---

## 5. 完整节点目录与 Asset 流图

### 5.1 Asset 类型

| Asset Key | Format | 说明 |
|-----------|--------|------|
| `text_input` | str | 用户文本输入 |
| `drawing_input` | image | 工程图纸文件 |
| `organic_input` | str+image | 有机建模输入 |
| `intent_spec` | json | 意图解析结果 |
| `drawing_spec` | json | 图纸分析结果 |
| `organic_spec` | json | 有机建模规格 |
| `confirmed_params` | json | 用户确认后的参数 |
| `step_model` | step | B-Rep CAD 模型 |
| `generated_code` | python | CadQuery 源码 |
| `raw_mesh` | glb/obj | AI 生成的原始网格 |
| `watertight_mesh` | stl | 修复后的水密网格 |
| `lattice_mesh` | stl | 晶格填充后的网格 |
| `oriented_mesh` | stl | 摆放优化后的网格 |
| `supported_mesh` | stl | 含支撑的网格 |
| `preview_glb` | glb | 3D 预览文件 |
| `dfam_glb` | glb | DfAM 热力图 |
| `printability_report` | json | 可打印性报告 |
| `export_bundle` | zip/dir | 最终导出包 |
| `gcode` | gcode | 切片文件 |

### 5.2 全量节点声明

**已实现（迁移）:**

| 节点 | requires | produces | input_types | strategies |
|------|----------|----------|-------------|-----------|
| `create_job` | `[]` | `[text_input\|drawing_input\|organic_input]` | all | — |
| `analyze_intent` | `[text_input]` | `[intent_spec]` | text | `default, two_pass, multi_vote` |
| `analyze_vision` | `[drawing_input]` | `[drawing_spec]` | drawing | `qwen_vl, gpt4o` |
| `analyze_organic` | `[organic_input]` | `[organic_spec]` | organic | `default` |
| `confirm_with_user` | `[[intent_spec, drawing_spec, organic_spec]]` | `[confirmed_params]` | all | — |
| `generate_step_text` | `[confirmed_params, intent_spec]` | `[step_model, generated_code]` | text | `template_first, llm_only` |
| `generate_step_drawing` | `[confirmed_params, drawing_spec]` | `[step_model, generated_code]` | drawing | `v2_pipeline, llm_direct` |
| `generate_organic_mesh` | `[confirmed_params, organic_spec]` | `[raw_mesh]` | organic | `tripo3d, hunyuan3d, auto` |
| `mesh_repair` | `[raw_mesh]` | `[watertight_mesh]` | organic | `pymeshlab, trimesh_voxel, meshlib` |
| `mesh_scale` | `[watertight_mesh]` | `[watertight_mesh]` | organic | `bbox_fit` |
| `boolean_cuts` | `[watertight_mesh]` | `[watertight_mesh]` | organic | `manifold3d` |
| `convert_preview` | `[[step_model]]` | `[preview_glb]` | text,drawing | `cadquery_native, trimesh` |
| `check_printability` | `[[step_model, watertight_mesh]]` | `[printability_report]` | all | `geometry_check, ai_check` |
| `analyze_dfam` | `[[step_model, watertight_mesh]]` | `[dfam_glb]` | all | `raycast, sampling` |
| `export_formats` | `[[step_model, watertight_mesh, oriented_mesh]]` | `[export_bundle]` | all | `trimesh, cadquery` |
| `finalize` | `[]` | `[]` | all | — |

**规划中（新增）:**

| 节点 | requires | produces | strategies |
|------|----------|----------|-----------|
| `orientation_optimizer` | `[[watertight_mesh, step_model]]` | `[oriented_mesh]` | `scipy, genetic` |
| `apply_lattice` | `[[watertight_mesh, step_model]]` | `[lattice_mesh]` | `tpms_gyroid, tpms_schwarz` |
| `slice_to_gcode` | `[[watertight_mesh, oriented_mesh]]` | `[gcode]` | `cura_engine, shapely` |

### 5.3 三条路径的 Asset 流图

```
TEXT 路径:
  create_job → [text_input]
    → analyze_intent → [intent_spec]
      → confirm_with_user → [confirmed_params]
        → generate_step_text → [step_model, generated_code]
          → convert_preview → [preview_glb]
          → check_printability → [printability_report]
          → analyze_dfam → [dfam_glb]
          → orientation_optimizer → [oriented_mesh]       (可选)
          → export_formats → [export_bundle]
          → slice_to_gcode → [gcode]                      (可选)
            → finalize

DRAWING 路径:
  create_job → [drawing_input]
    → analyze_vision → [drawing_spec]
      → confirm_with_user → [confirmed_params]
        → generate_step_drawing → [step_model, generated_code]
          → (同 TEXT 后半程)

ORGANIC 路径:
  create_job → [organic_input]
    → analyze_organic → [organic_spec]
      → confirm_with_user → [confirmed_params]
        → generate_organic_mesh → [raw_mesh]
          → mesh_repair → [watertight_mesh]
          → mesh_scale → [watertight_mesh]                (可选)
          → boolean_cuts → [watertight_mesh]              (可选)
          → check_printability → [printability_report]
          → analyze_dfam → [dfam_glb]
          → orientation_optimizer → [oriented_mesh]       (可选)
          → export_formats → [export_bundle]
          → slice_to_gcode → [gcode]                      (可选)
            → finalize
```

精密路径和有机路径在后处理阶段**自然归一** — `check_printability` 等节点通过 OR 依赖同时接受 `step_model` 和 `watertight_mesh`。

---

## 6. 节点配置 UI 设计

### 6.1 整体布局

```
┌─────────────────────────────────────────────────────────────┐
│  任务创建                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │ 1. 输入   │→│ 2. 确认   │→│ 3. 管线   │   ← 当前步骤      │
│  └──────────┘  └──────────┘  └──────────┘                   │
│                                                              │
│  ┌─── 预设选择 ─────────────────────────────────────────┐    │
│  │  ⚡ 快速    🎯 均衡(默认)    🔬 精密    ⚙️ 自定义    │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─── 管线流程图 ──────────────────┐  ┌─── 节点详情 ────┐   │
│  │  纵向 DAG 展示启用节点链        │  │  选中节点的配置  │   │
│  │  固定节点: 实色不可禁用          │  │  面板           │   │
│  │  可选节点: 开关切换              │  │                  │   │
│  │  禁用节点: 灰色半透明占位        │  │                  │   │
│  └──────────────────────────────────┘  └──────────────────┘   │
│                                                              │
│  ┌─── 依赖校验状态栏 ───────────────────────────────────┐    │
│  │  ✓ 管线配置有效 · 8 个节点启用 · 预计耗时 45-90s      │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 节点详情面板

```
┌──────────────────────────────────────┐
│  🌡️ DfAM 分析  (analyze_dfam)       │
│  ─────────────────────────────────── │
│  状态: ✓ 启用                 [关闭] │
│                                      │
│  ── 策略选择 ──                      │
│  ┌────────────┐  ┌────────────┐      │
│  │▶ Ray-cast  │  │  Sampling  │      │
│  │  (推荐)    │  │  (快速)    │      │
│  └────────────┘  └────────────┘      │
│                                      │
│  ── 参数配置 ──                      │
│  壁厚阈值        [1.0] mm    ⓘ      │
│  悬垂角度阈值    [45]  °     ⓘ      │
│  最大顶点数      [50000]     ⓘ      │
│                                      │
│  ── 输入/输出 ──                     │
│  输入: step_model 或 watertight_mesh │
│  输出: dfam_glb, dfam_stats          │
│                                      │
│  ── 说明 ──                          │
│  逐顶点壁厚和悬垂角分析。            │
│  失败不中断管线。                     │
│  预计耗时: 2-5s · 依赖: trimesh      │
└──────────────────────────────────────┘
```

信息来源：

| UI 区域 | 数据来源 |
|---------|---------|
| 策略卡片 | `NodeDescriptor.strategies` |
| 参数表单 | `config_model` 的 `Field(description=...)` |
| 输入/输出 | `NodeDescriptor.requires/produces` |
| 说明文字 | `NodeDescriptor.description` |
| 预计耗时 | `NodeDescriptor.estimated_duration` |
| 依赖状态 | `Strategy.check_available()` |

### 6.3 预设系统

```python
PIPELINE_PRESETS = {
    "fast": {
        "analyze_intent": {"strategy": "default"},
        "generate_step_text": {"strategy": "template_first", "best_of_n": 1},
        "convert_preview": {"enabled": True},
        "check_printability": {"enabled": False},
        "analyze_dfam": {"enabled": False},
        "orientation_optimizer": {"enabled": False},
        "slice_to_gcode": {"enabled": False},
    },
    "balanced": {
        "generate_step_text": {"strategy": "template_first", "best_of_n": 3},
        "convert_preview": {"enabled": True},
        "check_printability": {"enabled": True},
        "analyze_dfam": {"enabled": True},
    },
    "full_print": {
        "generate_step_text": {"strategy": "template_first", "best_of_n": 3},
        "check_printability": {"enabled": True},
        "analyze_dfam": {"enabled": True},
        "orientation_optimizer": {"enabled": True, "strategy": "scipy"},
        "slice_to_gcode": {"enabled": True, "strategy": "cura_engine"},
    },
}
```

修改任意节点参数后预设自动切换为 `custom`。

### 6.4 运行时监控

执行中，配置流程图变为实时监控视图。每个节点框显示：
- 状态图标：✅ 完成 / ⏳ 执行中 / ⏸ 等待 / ❌ 失败 / ⏭ 跳过
- 耗时：完成后显示实际耗时
- reasoning 摘要：hover 展示
- 点击已完成节点可查看详细输出

数据来源：现有 `node.started` / `node.completed` / `node.failed` SSE 事件。

### 6.5 实时校验

底部状态栏调用 `POST /api/v1/pipeline/validate` 实时反馈：
- `✓ 管线配置有效 · 8 个节点启用 · 预计耗时 45-90s`
- `⚠ orientation_optimizer 需要 watertight_mesh，请启用 mesh_repair`
- `✗ 两个节点同时产出 gcode，存在冲突`

---

## 7. 后端 API 变更

### 7.1 新增端点

```
GET  /api/v1/pipeline/nodes
     → 返回所有注册节点描述符（名称、策略列表、配置 schema、依赖关系）

POST /api/v1/pipeline/validate
     body: { input_type: "text", config: {...} }
     → DependencyResolver 校验，返回有序节点列表 + 校验结果

GET  /api/v1/pipeline/presets
     → 返回所有预设配置
```

### 7.2 现有端点改造

```
POST /api/v1/jobs
     pipeline_config 升级:
     旧: {"preset": "balanced", "best_of_n": 3}
     新: {"preset": "balanced", "nodes": {"analyze_dfam": {"enabled": true}, ...}}
     兼容层: 检测旧格式 → 迁移函数转换

GET  /api/v1/jobs/{id}
     新增字段:
     - pipeline_topology: 实际执行的有序节点列表
     - node_trace: 每个节点的执行记录
```

---

## 8. 文件结构

```
backend/graph/
├── registry.py              # NodeRegistry + @register_node 装饰器
├── descriptor.py            # NodeDescriptor, NodeStrategy, NodeResult
├── context.py               # NodeContext, AssetRegistry, AssetEntry
├── resolver.py              # DependencyResolver + ResolvedPipeline
├── builder.py               # PipelineBuilder（从 ResolvedPipeline 动态生成图）
├── state.py                 # PipelineState（替代 CadJobState）
├── compat.py                # 旧 CadJobState ↔ 新 PipelineState 兼容层
├── presets.py               # PIPELINE_PRESETS
├── discovery.py             # discover_nodes() 自动扫描
│
├── nodes/                   # 每个文件一个节点（自注册）
│   ├── create_job.py
│   ├── analyze_intent.py
│   ├── analyze_vision.py
│   ├── analyze_organic.py
│   ├── confirm.py
│   ├── generate_step_text.py
│   ├── generate_step_drawing.py
│   ├── generate_organic_mesh.py
│   ├── mesh_repair.py
│   ├── mesh_scale.py
│   ├── boolean_cuts.py
│   ├── convert_preview.py
│   ├── check_printability.py
│   ├── analyze_dfam.py
│   ├── export_formats.py
│   ├── finalize.py
│   ├── orientation_optimizer.py    # 规划
│   ├── apply_lattice.py            # 规划
│   └── slice_to_gcode.py           # 规划
│
├── strategies/              # 策略实现
│   ├── mesh_repair/
│   │   ├── pymeshlab_strategy.py
│   │   ├── trimesh_voxel_strategy.py
│   │   └── meshlib_strategy.py
│   ├── slicing/
│   │   ├── cura_engine_strategy.py
│   │   └── shapely_strategy.py
│   └── orientation/
│       ├── scipy_strategy.py
│       └── genetic_strategy.py
│
└── configs/                 # 节点配置模型
    ├── base.py              # BaseNodeConfig
    ├── analyze.py
    ├── generate.py
    ├── mesh_repair.py
    ├── orientation.py
    ├── slicing.py
    └── dfam.py
```

**新增节点的完整步骤**：
1. `configs/` 下新建配置模型
2. `strategies/` 下新建策略实现
3. `nodes/` 下新建节点文件，用 `@register_node` 装饰
4. 完成。无需改 builder、state、routing

---

## 9. 迁移策略

### 9.1 现有节点迁移

| 现有节点 | 变更说明 |
|---------|---------|
| `create_job_node` | `is_entry=True`，逻辑不变 |
| `analyze_intent_node` | 原 `pipeline_config` 的 `ocr_assist` / `two_pass_analysis` / `multi_model_voting` 下沉为策略 |
| `analyze_vision_node` | 同上 |
| `generate_step_text_node` | 原 `SpecCompiler` 的模板/LLM 路径变为策略 `template_first` / `llm_only` |
| `generate_organic_mesh_node` | 原 provider 选择变为策略 `tripo3d` / `hunyuan3d` / `auto` |
| `postprocess_organic_node` | **拆分为** `mesh_repair` + `mesh_scale` + `boolean_cuts` + `export_formats` 四个独立节点 |
| `check_printability_node` | OR 依赖，精密+有机共享 |
| `analyze_dfam_node` | OR 依赖，精密+有机共享 |
| `finalize_node` | 从 `state["assets"]` 收集产物写 DB |

### 9.2 兼容层

`backend/graph/compat.py` 提供：
- 旧 `PipelineConfig` → 新格式转换函数
- 旧 API 请求格式检测与自动迁移
- 旧测试中 `CadJobState` → `PipelineState` 映射辅助
