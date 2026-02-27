# cad3dify V3 设计文档

> **提案文档:** [proposal.md](./proposal.md)
> **版本**: v1
> **日期**: 2026-02-26

---

## ADR-1: CAD 内核选择 — CadQuery/OCCT

**决策：** 继续使用 CadQuery 2.x (基于 OCCT)，不迁移到 Build123d 或 OpenSCAD。

**理由：**
- CadQuery 拥有 ~450K LLM 训练数据（Text2CAD 170K + Text-to-CadQuery 170K + CAD-Coder 110K），Build123d 近乎零
- OCCT 支持 BREP/STEP/NURBS，OpenSCAD 的 CGAL 不支持 STEP
- V2 知识库（20 示例 + 7 策略）全部基于 CadQuery，迁移 = 重写（2-4 周）
- 通过 `CADBackend` 接口层预留未来替换能力

**替代方案被否决：**
- Build123d：API 更 Pythonic 但 LLM 生态劣势致命
- OpenSCAD：社区最大但无 STEP → 不适合工业用途

---

## ADR-2: 前后端分离架构

**决策：** 将 cad3dify 从纯 Python 库重构为前后端分离应用。

**理由：**
- V3 需要 3D 预览、参数滑块、知识库管理等丰富 UI
- CAD 计算必须在后端执行（CadQuery 依赖 OCCT C++ 库）
- 前端 Three.js 可加载 STL/glTF 实现流畅 3D 交互

**架构：**
```
Frontend (:3001)                    Backend (:8780)
React + Three.js + TypeScript       FastAPI + CadQuery + LangChain
     │                                    │
     ├─ 对话输入组件                       ├─ /api/generate (SSE)
     ├─ 参数表单 + 滑块                    ├─ /api/templates (CRUD)
     ├─ 3D Viewer (R3F)                   ├─ /api/standards (查询)
     ├─ 知识库管理                         ├─ /api/export (转换)
     └─ 可打印性报告                       └─ /api/benchmark (评测)
```

---

## ADR-3: 参数化模板 vs LLM 自由生成 — 双轨策略

**决策：** 参数化模板优先，LLM 自由生成作为 fallback。

**理由：**
- 模板消除结构性代码错误（模板预验证 → 参数注入 → 精度 ~99%）
- 但模板无法覆盖所有零件类型，需要 LLM 自由生成兜底
- 随着模板库扩展，LLM 自由生成的比例会逐渐降低

**选择逻辑：**
```python
def select_generation_strategy(intent: IntentSpec) -> Strategy:
    # 1. 精确匹配参数化模板
    template = template_engine.find_exact_match(intent.part_type, intent.known_params)
    if template:
        return TemplateStrategy(template)

    # 2. 模糊匹配 + 参数适配
    candidates = template_engine.find_similar(intent.part_type)
    if candidates:
        return AdaptiveTemplateStrategy(candidates[0], intent)

    # 3. Fallback: LLM 自由生成（RAG 增强）
    return LLMGenerationStrategy(intent, rag_enabled=True)
```

---

## ADR-4: 3D 预览方案 — 后端转换 + Three.js

**决策：** STEP → glTF 转换在后端完成，Three.js 加载 glTF 渲染。

**理由：**
- opencascade.js (WASM) 体积大（~30MB）且性能受限
- 后端 CadQuery/OCCT 已有 STEP → STL 能力，STL → glTF 可用 trimesh
- Three.js 加载 glTF 是最成熟的方案
- 参数滑块调整时，后端重新生成 + 增量更新预览

**替代方案被否决：**
- opencascade.js 浏览器端：体积大、首次加载慢、精度问题
- 纯 STL Viewer：丢失 STEP 的面/边信息

---

## ADR-5: 向量检索方案 — pgvector

**决策：** 使用 PostgreSQL pgvector 扩展实现向量检索。

**理由：**
- 不引入新基础设施（已有 PostgreSQL）
- 170K 规模的向量检索 pgvector 性能完全足够
- 支持 IVFFlat/HNSW 索引，查询延迟 < 10ms

**替代方案被否决：**
- Milvus/Qdrant：额外运维成本，规模不需要
- ChromaDB：轻量但不支持生产级部署

---

## ADR-6: 流程自由可配置 — 少即是多

**决策：** 管道中每个增强步骤均可独立开关，前端用 Tooltip（? 图标 hover 提示）说明每个选项的作用、适用场景和性能代价。

**核心原则：**

1. **每步可选** — 所有增强步骤（Best-of-N、多视角、OCR、多模型投票、RAG、可打印性检查等）均有独立开关，用户可根据场景自由组合
2. **合理默认** — 提供三个预设："快速模式"（最少步骤）、"均衡模式"（推荐，平衡质量与速度）、"精确模式"（全部增强），也可自定义
3. **透明代价** — 每个选项的 Tooltip 必须说明：① 做什么 ② 适合什么场景 ③ 额外耗时/成本
4. **渐进披露** — 基础用户看到简洁界面 + 预设模式；高级用户展开看到全部开关

**理由：**
- 过多步骤叠加不一定效果更好，反而可能增加延迟、引入噪声
- 不同零件复杂度需要不同增强组合：简单板件无需多模型投票，精密齿轮需要全部增强
- 用户是最终使用者，应有权控制质量/速度/成本的平衡

**PipelineConfig 数据模型：**

```python
class PipelineConfig(BaseModel):
    """管道配置 — 每个增强步骤独立可控"""

    # --- 预设模式 ---
    preset: Literal["fast", "balanced", "precise", "custom"] = "balanced"

    # --- Stage 1: 图纸分析增强（仅图纸输入时生效）---
    ocr_assist: bool = False            # OCR 辅助标注提取
    two_pass_analysis: bool = False     # 两阶段分析（全局+局部）
    multi_model_voting: bool = False    # 多 VL 模型投票
    self_consistency_runs: int = 1      # Self-consistency 次数（1=关闭）

    # --- Stage 2: 代码生成 ---
    best_of_n: int = 1                  # Best-of-N 候选数（1=关闭）
    rag_enabled: bool = True            # RAG 检索增强
    api_whitelist: bool = True          # CadQuery API 白名单约束
    ast_pre_check: bool = True          # 执行前 AST 静态检查

    # --- Stage 3: 验证 ---
    volume_check: bool = True           # 体积估算验证
    topology_check: bool = True         # 拓扑验证
    cross_section_check: bool = False   # 截面分析

    # --- Stage 4: 修复循环 ---
    max_refinements: int = 3            # 最大修复轮数
    multi_view_render: bool = True      # 多视角渲染
    structured_feedback: bool = True    # 结构化 VL 反馈（JSON issues）
    rollback_on_degrade: bool = True    # 退化时自动回滚
    contour_overlay: bool = False       # 轮廓叠加比对

    # --- Stage 5: 输出 ---
    printability_check: bool = False    # 可打印性检查
    output_formats: list[str] = ["step"]  # 输出格式

# 预设配置
PRESETS = {
    "fast": PipelineConfig(
        preset="fast",
        best_of_n=1, rag_enabled=False, multi_view_render=False,
        volume_check=False, topology_check=False,
        max_refinements=1, output_formats=["step"],
    ),
    "balanced": PipelineConfig(
        preset="balanced",
        best_of_n=3, rag_enabled=True, multi_view_render=True,
        volume_check=True, topology_check=True,
        max_refinements=3, output_formats=["step", "stl"],
    ),
    "precise": PipelineConfig(
        preset="precise",
        best_of_n=5, rag_enabled=True, multi_view_render=True,
        ocr_assist=True, two_pass_analysis=True,
        multi_model_voting=True, self_consistency_runs=3,
        volume_check=True, topology_check=True, cross_section_check=True,
        structured_feedback=True, contour_overlay=True,
        printability_check=True, output_formats=["step", "stl", "3mf"],
    ),
}
```

**Tooltip 规范：**

每个管道选项必须配一个 `TooltipSpec`，前端渲染为 `?` 图标 hover 弹出：

```python
class TooltipSpec(BaseModel):
    title: str          # "多路生成 (Best-of-N)"
    description: str    # "生成 N 份候选代码并择优。N=3 时正确率从 40% 提升到 78%。"
    when_to_use: str    # "复杂零件、首次正确率不高时推荐开启"
    cost: str           # "耗时 ×N，Token ×N"
    default: str        # "balanced 模式: N=3"
```

前端 Tooltip 统一使用 Ant Design 的 `<Tooltip>` 组件，图标统一为 `<QuestionCircleOutlined />`。

**PipelineConfig Stage ↔ 后端模块映射：**

| PipelineConfig Stage | 对应后端模块 | 管道位置 |
|---------------------|-------------|---------|
| Stage 1: 图纸分析增强 | `drawing_analyzer.py` | `pipeline.stages.AnalysisStage` |
| Stage 2: 代码生成 | `code_generator.py` + `template_engine.py` | `pipeline.stages.GenerationStage` |
| Stage 3: 验证 | `validators.py` | `pipeline.stages.ValidationStage` |
| Stage 4: 修复循环 | `smart_refiner.py` + `render.py` | `pipeline.stages.RefinementStage` |
| Stage 5: 输出 | `format_exporter.py` + `printability.py` | `pipeline.stages.OutputStage` |

每个 Stage 在 `pipeline.py` 中根据 `PipelineConfig` 的对应开关决定是否执行该步骤。

---

## 核心模块设计

### 1. IntentParser — 意图解析器

**职责：** 将自然语言输入解析为结构化 IntentSpec。

```python
class IntentSpec(BaseModel):
    """用户意图的结构化表示"""
    part_category: str              # "法兰盘" / "轴" / "支架"
    part_type: PartType | None      # 映射到已知类型，未知则 None
    known_params: dict[str, float]  # 用户明确给出的参数 {"外径": 100}
    missing_params: list[str]       # 需要补全的参数 ["厚度", "孔径"]
    constraints: list[str]          # 用户约束 ["需要和M10螺栓配合"]
    reference_image: str | None     # 参考图片路径
    confidence: float               # 整体置信度 0-1
    raw_text: str                   # 原始输入文本

class IntentParser:
    """LLM 驱动的意图解析器 — 只做理解，不做计算"""

    async def parse(self, user_input: str, image: bytes | None = None) -> IntentSpec:
        # 1. LLM 提取零件类型 + 已知参数
        # 2. 查询 PartType 映射表
        # 3. 根据 PartType 的 ParamDefinition 识别缺失参数
        # 4. 提取用户约束条件
        ...
```

**LLM 边界：** 只做意图理解和参数提取，不做数值计算或代码生成。

### 1.1 PreciseSpec — 精确参数规范

**职责：** 所有参数精确确定后的完整规范，继承 DrawingSpec 并扩展。

```python
class PreciseSpec(DrawingSpec):
    """所有参数精确确定的零件规范（IntentSpec 经用户确认后的产物）"""
    source: Literal["text_input", "drawing_input", "image_input"]
    confirmed_by_user: bool = True    # 参数是否经过用户确认
    intent: IntentSpec | None = None  # 原始意图（可追溯）
    recommendations_applied: list[str] = []  # 应用了哪些工程标准推荐
```

**转换链路：**
```
用户自然语言输入 → IntentParser → IntentSpec（部分参数）
    → EngineeringStandards.recommend_params() → 推荐补全
    → 用户确认/修改 → PreciseSpec（所有参数精确）
    → ParametricTemplateEngine / CodeGenerator → CadQuery 代码
```

### 2. ParametricTemplateEngine — 参数化模板引擎

**职责：** 管理参数化模板库，通过精确参数注入生成 CadQuery 代码。

```python
class ParamDefinition(BaseModel):
    name: str                       # "outer_diameter"
    display_name: str               # "外径"
    unit: str                       # "mm"
    param_type: Literal["float", "int", "bool"]
    min_value: float | None
    max_value: float | None
    default: float | None
    depends_on: list[str] = []      # 依赖的其他参数
    standard_ref: str | None        # 关联的工程标准 "GB/T 9119"

class ParametricTemplate(BaseModel):
    name: str                       # "standard_flange"
    display_name: str               # "标准法兰盘"
    part_type: PartType
    parameters: list[ParamDefinition]
    code_template: str              # Jinja2 模板（CadQuery 代码）
    validation_rules: list[str]     # 参数间约束规则表达式
    preview_image: str | None       # 预览缩略图
    tags: list[str]                 # ["法兰", "圆盘", "螺栓孔"]

class ParametricTemplateEngine:
    def find_match(self, part_type: PartType, params: dict) -> ParametricTemplate | None: ...
    def generate_code(self, template: ParametricTemplate, params: dict) -> str: ...
    def validate_params(self, template: ParametricTemplate, params: dict) -> list[str]: ...
    def list_templates(self, part_type: PartType | None = None) -> list[ParametricTemplate]: ...
    def create_template(self, template: ParametricTemplate) -> None: ...
    def update_template(self, name: str, template: ParametricTemplate) -> None: ...
    def delete_template(self, name: str) -> None: ...
```

**Jinja2 模板示例（法兰盘）：**

```yaml
# backend/knowledge/templates/standard_flange.yaml
name: standard_flange
display_name: "标准法兰盘"
part_type: ROTATIONAL
parameters:
  - name: outer_diameter
    display_name: "外径"
    unit: mm
    param_type: float
    min_value: 30
    max_value: 500
    default: 100
  - name: thickness
    display_name: "厚度"
    unit: mm
    param_type: float
    min_value: 5
    max_value: 50
    default: 12
  - name: hole_count
    display_name: "螺栓孔数"
    unit: ""
    param_type: int
    min_value: 4
    max_value: 24
    default: 6
  - name: hole_diameter
    display_name: "螺栓孔径"
    unit: mm
    param_type: float
    min_value: 5
    max_value: 30
    default: 11
  - name: pcd
    display_name: "螺栓孔中心圆直径"
    unit: mm
    param_type: float
    min_value: 20
    max_value: 450
    depends_on: [outer_diameter]
    standard_ref: "GB/T 9119"
  - name: center_hole_diameter
    display_name: "中心孔直径"
    unit: mm
    param_type: float
    min_value: 10
    max_value: 200
    default: 30
validation_rules:
  - "pcd < outer_diameter"
  - "hole_diameter < (3.14159 * pcd / hole_count)"  # 孔不重叠
code_template: |
  import cadquery as cq
  result = (
      cq.Workplane("XY")
      .circle({{ outer_diameter / 2 }})
      .extrude({{ thickness }})
      .faces(">Z").workplane()
      .polygon({{ hole_count }}, {{ pcd }}, forConstruction=True)
      .vertices()
      .hole({{ hole_diameter }})
      .faces(">Z").workplane()
      .circle({{ center_hole_diameter / 2 }})
      .cutThruAll()
  )
```

**与 V2 TaggedExample 的区别：**

| 维度 | TaggedExample | ParametricTemplate |
|------|---------------|-------------------|
| 代码 | 固定值示例 | Jinja2 参数化模板 |
| 精度 | 依赖 LLM 模仿 | 模板预验证 + 参数注入 |
| 覆盖 | 每个尺寸一个示例 | 同模板覆盖所有尺寸 |
| CRUD | 代码文件，无 UI | API + UI 管理 |

### 3. EngineeringStandards — 工程标准知识库

**职责：** 基于工程标准推荐参数默认值，检查参数间一致性。

```python
class ParamRecommendation(BaseModel):
    param_name: str             # "孔径"
    recommended_value: float    # 11.0
    reason: str                 # "M10 螺栓通孔标准直径 (GB/T 5277)"
    standard_ref: str           # "GB/T 5277"
    confidence: float           # 0.95

class EngineeringStandards:
    def recommend_params(
        self, part_category: str, known_params: dict
    ) -> list[ParamRecommendation]: ...

    def check_constraints(
        self, params: dict
    ) -> list[ConstraintViolation]: ...

    def query_standard(
        self, standard_id: str
    ) -> StandardInfo: ...
```

**初始覆盖的标准类别：**

| 标准类别 | 示例 | 用途 |
|---------|------|------|
| 螺栓/螺母 | M6-M30 通孔直径、沉孔尺寸 | 孔径推荐 |
| 法兰 | GB/T 9119, ASME B16.5 | PCD、螺栓数推荐 |
| 配合公差 | H7/h6, H7/p6 | 轴孔配合尺寸 |
| 键/键槽 | GB/T 1096 | 键槽宽度、深度 |
| 齿轮 | 模数系列、压力角 | 齿轮参数推荐 |
| 3D 打印约束 | FDM/SLA 最小壁厚 | 可打印性检查 |

### 4. PrintabilityChecker — 可打印性检查器

```python
class PrintProfile(BaseModel):
    name: str                   # "fdm_standard"
    technology: str             # "FDM" / "SLA" / "SLS"
    min_wall: float             # 最小壁厚 mm
    max_overhang: float         # 最大悬挑角度 degrees
    min_hole: float             # 最小孔径 mm
    min_feature: float          # 最小特征尺寸 mm
    build_volume: tuple[float, float, float]  # (x, y, z) mm
    layer_height: float         # 层高 mm

class PrintabilityIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    category: str               # "wall_thickness" / "overhang" / "hole_size"
    description: str
    location: str | None        # 几何位置描述
    suggestion: str             # 修复建议

class PrintabilityResult(BaseModel):
    printable: bool
    issues: list[PrintabilityIssue]
    recommended_orientation: tuple[float, float, float] | None
    estimated_material_g: float | None
    estimated_time_min: float | None

class PrintabilityChecker:
    def check(self, step_path: str, profile: PrintProfile) -> PrintabilityResult: ...
```

### 5. FormatExporter — 格式导出器

```python
class ExportConfig(BaseModel):
    format: Literal["stl", "3mf", "gltf"]
    linear_deflection: float = 0.1      # mm
    angular_deflection: float = 0.5     # degrees
    include_colors: bool = False

class FormatExporter:
    def export(self, step_path: str, output_path: str, config: ExportConfig) -> None: ...
    def to_gltf_for_preview(self, step_path: str) -> bytes: ...
```

### 6. BenchmarkRunner — 评测基准

```python
class BenchmarkCase(BaseModel):
    case_id: str                # "case_001_flange"
    drawing_path: str           # 输入图纸路径
    expected_spec: dict         # 期望的 DrawingSpec
    expected_bbox: dict         # 期望包围盒 {xlen, ylen, zlen, tolerance_pct}

class BenchmarkMetrics(BaseModel):
    compile_rate: float         # 编译通过率
    type_accuracy: float        # 类型识别准确率
    param_accuracy_p50: float   # 参数准确率中位数
    bbox_match_rate: float      # 包围盒匹配率
    avg_duration_s: float       # 平均耗时
    avg_tokens: int             # 平均 token 消耗

class BenchmarkRunner:
    async def run(self, dataset_dir: str, workers: int = 4) -> BenchmarkReport: ...
    async def run_spec_only(self, dataset_dir: str) -> BenchmarkReport: ...
```

---

## 数据流

### 自然语言输入流程（Phase 4 完整实现后）

```
用户输入: "做一个法兰盘，外径100，6个螺栓孔"
    │
    ├─ 1. IntentParser.parse()
    │   → IntentSpec(part_type=ROTATIONAL, known_params={外径:100, 孔数:6},
    │                missing_params=[厚度, 孔径, PCD, 通孔直径])
    │
    ├─ 2. EngineeringStandards.recommend_params()
    │   → [ParamRecommendation(厚度=12, reason="GB/T 9119 PN16"),
    │      ParamRecommendation(孔径=11, reason="M10 通孔标准"),
    │      ParamRecommendation(PCD=70, reason="GB/T 9119 DN50")]
    │
    ├─ 3. 前端展示参数确认表 → 用户确认/修改
    │   → PreciseSpec(所有参数精确确定)
    │
    ├─ 4. ParametricTemplateEngine.find_match() → 找到 "standard_flange" 模板
    │   → generate_code(template, params) → CadQuery 代码
    │
    ├─ 5. agents.execute() → STEP 文件
    │
    ├─ 6. Validators
    │   ├─ validate_bounding_box() ✅
    │   ├─ estimate_volume() ✅
    │   └─ count_topology() ✅
    │
    ├─ 7. PrintabilityChecker.check() → PrintabilityResult
    │
    └─ 8. FormatExporter
        ├─ → STEP 文件
        ├─ → STL/3MF 文件
        ├─ → glTF（前端预览）
        └─ → 参数化源码（可编辑）
```

### 图纸输入流程（V2 兼容，Phase 2 增强后）

```
工程图纸输入
    │
    ├─ 1. DrawingAnalyzer (VL + CoT) → DrawingSpec
    │   [Phase 5: + OCR 辅助 + 多模型投票]
    │
    ├─ 2. ModelingStrategist → 选择策略 + 示例
    │   [Phase 3: → TemplateSelector 优先匹配模板]
    │
    ├─ 3. CodeGenerator (Best-of-N, N=3)
    │   ├─ 候选 1 → 执行 → 打分
    │   ├─ 候选 2 → 执行 → 打分
    │   └─ 候选 3 → 执行 → 打分
    │   → 取最高分候选
    │
    ├─ 4. SmartRefiner (多视角渲染 + 回滚机制)
    │   ├─ 渲染 4 视角（正面/俯视/侧面/等轴测）
    │   ├─ VL 比较 → 结构化 issues JSON
    │   ├─ Coder 修复 → 回滚检查（退化 > 10% 则回滚）
    │   └─ 循环直到 PASS 或达到 max_rounds
    │
    ├─ 5. Validators (增强)
    │   ├─ validate_code_params() → 诊断上下文
    │   ├─ validate_bounding_box() → 诊断上下文
    │   ├─ estimate_volume() → 体积偏差检查
    │   └─ count_topology() → 拓扑验证
    │
    └─ 6. Export (STEP + STL/3MF + glTF)
```

---

## API 设计

### 生成 API（SSE 流式）

```
POST /api/generate
Content-Type: application/json

{
  "input_type": "text" | "drawing" | "text_with_image",
  "text": "做一个法兰盘，外径100",
  "params": {"外径": 100, "孔数": 6},        // 可选
  "image": "base64...",                      // 可选
  "print_profile": "fdm_standard",           // 可选
  "pipeline_config": {                       // 管道配置（可选，默认 balanced 预设）
    "preset": "balanced",                    // "fast" | "balanced" | "precise" | "custom"
    // --- custom 模式下可逐项覆盖 ---
    "best_of_n": 3,
    "rag_enabled": true,
    "multi_view_render": true,
    "ocr_assist": false,
    "volume_check": true,
    "topology_check": true,
    "printability_check": false,
    "output_formats": ["step", "stl"]
  }
}

GET /api/pipeline/tooltips                   // 获取所有管道选项的 Tooltip 说明
→ { "best_of_n": { "title": "多路生成", "description": "...", "cost": "..." }, ... }

→ SSE Events:
event: intent
data: {"part_type": "rotational", "known_params": {...}, "missing_params": [...]}

event: params_confirmation
data: {"params": [...], "recommendations": [...]}

event: generation_progress
data: {"stage": "code_generation", "progress": 0.3, "message": "生成候选代码 2/3"}

event: refinement_progress
data: {"round": 2, "max_rounds": 3, "status": "improving", "score_delta": +0.15, "message": "第2轮修复：孔位置偏移已修正"}

event: preview
data: {"gltf_url": "/api/files/xxx.gltf", "bbox": {...}}

event: validation
data: {"bbox": "pass", "volume": "pass", "topology": "pass"}

event: printability
data: {"printable": true, "issues": [...]}

event: complete
data: {"step_url": "...", "stl_url": "...", "3mf_url": "...", "code": "..."}
```

### 生成任务会话协议

自然语言输入时，`/api/generate` 返回 `job_id`，流程在 `params_confirmation` 阶段暂停等待用户确认：

```
POST /api/generate → SSE 流
  event: job_created     data: {"job_id": "xxx"}
  event: intent          data: {...}
  event: params_confirmation  data: {"job_id": "xxx", "params": [...], "recommendations": [...]}
  ← 流暂停，等待用户确认 →

POST /api/generate/{job_id}/confirm
{
  "confirmed_params": {"外径": 100, "厚度": 12, ...}
}
→ 恢复 SSE 流
  event: generation_progress  data: {...}
  event: preview              data: {...}
  event: complete             data: {...}
```

**状态机：**
```
CREATED → INTENT_PARSED → AWAITING_CONFIRMATION → GENERATING → REFINING → COMPLETED
                                                                          ↗
                                                  → VALIDATION_FAILED → (自动重试或终止)
```

图纸输入模式无需暂停确认，整个流程一次性完成（除非 `PipelineConfig` 开启了手动确认）。

### 模板 API

```
GET    /api/templates                     # 列表
GET    /api/templates/{name}              # 详情
POST   /api/templates                     # 创建
PUT    /api/templates/{name}              # 更新
DELETE /api/templates/{name}              # 删除
POST   /api/templates/{name}/validate     # 验证模板 + 参数
POST   /api/templates/{name}/preview      # 用参数生成预览
```

### 工程标准 API

```
GET    /api/standards                     # 标准分类列表
GET    /api/standards/{category}          # 某类标准详情
POST   /api/standards/recommend           # 基于已知参数推荐
POST   /api/standards/check               # 约束检查
```

### 导出 API

```
POST   /api/export
{
  "step_path": "...",
  "format": "stl" | "3mf" | "gltf",
  "config": {"linear_deflection": 0.1, "angular_deflection": 0.5}
}
```

### 评测 API

```
POST   /api/benchmark/run
{
  "dataset": "v1",
  "workers": 4,
  "spec_only": false
}
→ SSE Events (进度 + 结果)

GET    /api/benchmark/history          # 历史评测报告列表
GET    /api/benchmark/history/{run_id} # 某次评测的详细报告
```

---

## 前端页面设计

### 页面结构

```
/                     → 首页（快速输入 + 最近生成历史）
/generate             → 生成工作台（对话 + 参数 + 3D 预览）
/templates            → 模板管理（列表 + 编辑器）
/templates/:name      → 模板详情（参数定义 + 代码 + 预览）
/standards            → 工程标准浏览
/benchmark            → 评测基准（运行 + 历史报告）
/settings             → 设置（LLM 配置 + 打印配置）
```

### 生成工作台布局

```
┌─────────────────────────────────────────────────────┐
│  Header: cad3dify                        [Settings] │
├─────────────────────────────────────────────────────┤
│  管道配置栏                                          │
│  [⚡快速] [⚖️均衡] [🎯精确] [⚙️自定义]              │
│  └─ 展开自定义（高级用户）:                           │
│     ☑ 多路生成(N=3) ⓘ  ☑ RAG增强 ⓘ  ☐ OCR辅助 ⓘ  │
│     ☑ 多视角渲染 ⓘ    ☑ 拓扑验证 ⓘ  ☐ 多模型投票 ⓘ│
│     ☑ 体积估算 ⓘ      ☐ 截面分析 ⓘ  ☐ 轮廓叠加 ⓘ  │
│     ☑ 回滚保护 ⓘ      ☐ 可打印性 ⓘ                 │
│     (ⓘ = hover 显示 Tooltip: 说明+适用场景+代价)     │
├──────────────────────┬──────────────────────────────┤
│                      │                              │
│  左侧面板            │  右侧 3D Viewer              │
│  ├─ 对话输入区       │  ├─ Three.js 3D 渲染         │
│  │  用户消息         │  │  旋转/缩放/平移            │
│  │  AI 响应          │  │  线框/实体切换             │
│  │  参数确认卡片     │  │  多视角快照               │
│  │  输入框           │  │                           │
│  │                   │  ├─ 参数滑块区               │
│  ├─ 参数面板         │  │  外径 [====|=====] 100mm  │
│  │  表单字段         │  │  厚度 [==|=========] 12mm │
│  │  推荐值标注       │  │  孔数 [===|======]  6     │
│  │  约束警告         │  │                           │
│  │                   │  ├─ 可打印性报告              │
│  └─ 输出下载区       │  │  ✅ 壁厚  ⚠️ 悬挑         │
│     STEP | STL | 3MF │  │  ✅ 孔径  ✅ 特征         │
│     代码 | 报告      │  │                           │
│                      │                              │
└──────────────────────┴──────────────────────────────┘
```

### 知识库管理页面

```
┌─────────────────────────────────────────────────────┐
│  模板管理                              [+ 新建模板] │
├──────────┬──────────────────────────────────────────┤
│ 类型筛选 │  模板列表                                 │
│          │  ┌─────────────────────────────────────┐ │
│ ☑ 旋转体 │  │ standard_flange        [编辑] [删除]│ │
│ ☑ 阶梯轴 │  │ 标准法兰盘 | 8 参数 | 3 约束        │ │
│ ☑ 板件   │  │ 最近验证: ✅ 通过                   │ │
│ ☑ 支架   │  ├─────────────────────────────────────┤ │
│ ☑ 壳体   │  │ stepped_shaft          [编辑] [删除]│ │
│ ☐ 齿轮   │  │ 阶梯轴 | 12 参数 | 5 约束          │ │
│          │  │ 最近验证: ⚠️ 1 警告                 │ │
│          │  └─────────────────────────────────────┘ │
└──────────┴──────────────────────────────────────────┘
```

---

## 目录结构（V3 重构后）

```
cad3dify/
├── backend/
│   ├── api/                        # FastAPI 路由
│   │   ├── generate.py             # 生成 API (SSE)
│   │   ├── templates.py            # 模板 CRUD API
│   │   ├── standards.py            # 工程标准 API
│   │   ├── export.py               # 格式导出 API
│   │   └── benchmark.py            # 评测 API
│   ├── core/                       # 核心引擎
│   │   ├── intent_parser.py        # Phase 4: IntentParser
│   │   ├── template_engine.py      # Phase 3: ParametricTemplateEngine
│   │   ├── code_generator.py       # V2 升级: Best-of-N
│   │   ├── smart_refiner.py        # V2 升级: 多视角 + 回滚
│   │   ├── drawing_analyzer.py     # V2 保留: VL 分析
│   │   ├── modeling_strategist.py  # V2 → TemplateSelector
│   │   ├── validators.py           # V2 + 体积/拓扑
│   │   ├── printability.py         # Phase 4: 可打印性
│   │   ├── format_exporter.py      # Phase 1: STL/3MF/glTF
│   │   └── engineering_standards.py # Phase 4: 工程标准
│   ├── knowledge/                  # 知识库
│   │   ├── templates/              # Phase 3: 参数化模板 (YAML/JSON)
│   │   ├── examples/               # V2 保留: TaggedExample
│   │   ├── standards/              # Phase 4: 工程标准数据
│   │   └── strategies/             # V2 保留: 建模策略
│   ├── pipeline/                   # 管道编排
│   │   ├── pipeline.py             # 主管道
│   │   └── stages.py               # Stage 定义
│   ├── models/                     # 数据模型
│   │   ├── intent.py               # IntentSpec, PreciseSpec
│   │   ├── drawing_spec.py         # V2 DrawingSpec (兼容)
│   │   ├── template.py             # ParametricTemplate, ParamDefinition
│   │   ├── pipeline_config.py      # PipelineConfig, TooltipSpec, PRESETS
│   │   ├── printability.py         # PrintProfile, PrintabilityResult
│   │   └── benchmark.py            # BenchmarkCase, BenchmarkMetrics
│   ├── infra/                      # 基础设施
│   │   ├── agents.py               # V2 保留: 代码执行器
│   │   ├── render.py               # V2 + 多视角渲染
│   │   ├── chat_models.py          # V2 保留: LLM 客户端
│   │   ├── image.py                # V2 保留: 图片处理
│   │   └── rag.py                  # Phase 5: RAG 检索
│   ├── benchmark/                  # 评测基准
│   │   ├── runner.py
│   │   ├── metrics.py
│   │   └── reporter.py
│   ├── config.py                   # 应用配置
│   ├── main.py                     # FastAPI 入口
│   └── v1/                         # V1 兼容 (fallback)
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Generate/           # 生成工作台
│   │   │   ├── Templates/          # 模板管理
│   │   │   ├── Standards/          # 工程标准
│   │   │   ├── Benchmark/          # 评测基准
│   │   │   └── Settings/           # 设置
│   │   ├── components/
│   │   │   ├── Viewer3D/           # Three.js 3D 预览组件
│   │   │   ├── ParamSlider/        # 参数滑块组件
│   │   │   ├── ParamForm/          # 参数表单组件
│   │   │   ├── ChatPanel/          # 对话面板
│   │   │   ├── PipelineConfigBar/  # 管道配置组件（预设+自定义+Tooltip）
│   │   │   ├── PrintReport/        # 可打印性报告
│   │   │   └── TemplateEditor/     # 模板编辑器
│   │   ├── hooks/
│   │   ├── services/               # API 客户端
│   │   └── types/                  # TypeScript 类型
│   ├── package.json
│   └── vite.config.ts
│
├── benchmarks/                     # 评测数据集
│   └── v1/
├── docs/
├── tests/
├── openspec/
└── pyproject.toml
```

---

## 迁移策略

### Phase 1 迁移路径

1. 创建 `backend/` 和 `frontend/` 目录结构
2. 将现有 `cad3dify/` 模块迁移到 `backend/core/` 和 `backend/infra/`
3. 保持 `import cad3dify` 兼容性（`backend/__init__.py` 重导出）
4. 添加 FastAPI 路由层
5. 创建 React 前端骨架

### 渐进式替换

| V2 模块 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---------|---------|---------|---------|---------|
| pipeline.py | 迁移 | +Best-of-N | +模板选择 | +意图解析 |
| validators.py | +体积估算 | +拓扑验证 | — | +可打印性 |
| render.py | +STL/glTF | +多视角 | — | — |
| knowledge/ | 迁移 | — | →模板引擎 | +标准库 |
| smart_refiner.py | 迁移 | +回滚+结构化 | — | — |
