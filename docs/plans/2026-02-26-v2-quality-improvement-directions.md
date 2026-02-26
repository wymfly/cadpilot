# V2 质量提升方向

> **状态:** 设计完成，按优先级分批实施
> **日期:** 2026-02-26
> **前置:** P0/P1 已实施，SmartRefiner 已重构为零风险模式

---

## 设计原则

**VL 是质量的唯一裁判。** SmartRefiner 的 Layer 1（静态参数校验）和 Layer 2（包围盒校验）
已重构为纯诊断模式——仅收集上下文注入 Coder 修复指令，不跳过 VL 调用。
这消除了静态校验过拟合导致跳过 VL 的风险。

质量上限由以下因素决定：

1. **DrawingSpec 提取准确率**（Stage 1）— 错误会雪崩传播
2. **代码生成首次正确率**（Stage 2）— 决定需要多少轮修复
3. **VL 对比识别能力**（Stage 4）— 发现不了就修不了
4. **知识库覆盖度**（Stage 1.5）— 示例质量直接影响代码质量

---

## Stage 1：图纸分析（VL → DrawingSpec）

### 1.1 OCR 辅助标注提取

**问题：** VL 模型"看"图纸时容易漏读小字标注（φ10、R5、公差等），
这是当前图纸分析失败的最常见原因。

**方案：**
1. 用 OCR 引擎（PaddleOCR / Tesseract）提取图纸上所有文本和数值
2. 解析尺寸标注格式（φ、R、×、±）提取结构化数值列表
3. 将 OCR 结果作为辅助输入注入 VL 的 prompt
4. VL 提取的 DrawingSpec 与 OCR 数值交叉验证，不一致的标为低置信度

**交叉验证规则：**
- VL 和 OCR 一致 → 高置信度，直接使用
- VL 有值但 OCR 未提取到 → 中置信度，保留 VL 结果
- OCR 有值但 VL 未提取到 → 低置信度，标注为 `needs_review`
- VL 和 OCR 值不一致 → 优先信 OCR 的数值、信 VL 的语义关系

**预估提升：** 高 — 标注漏读是当前最大失败源
**复杂度：** 中等 — 需要 OCR 引擎集成 + 标注格式解析

### 1.2 多模型投票

**问题：** 单一 VL 模型的盲区固定，某些图纸风格/布局下稳定犯错。

**方案：**
1. 同一图纸并行调用 2-3 个 VL 模型（qwen-vl-max、GPT-4o、Claude）
2. 各模型独立输出 DrawingSpec
3. 对每个字段取多数一致值
4. 不一致的字段标为低置信度

**投票策略：**
- 数值字段（尺寸）：3 个值取中位数，偏差 > 20% 的标为低置信度
- 枚举字段（part_type、method）：取多数票，无多数时按模型优先级
- 列表字段（profile layers、features）：以结构最完整的为准

**预估提升：** 中高 — 不同模型犯不同错误
**复杂度：** 低 — 并行调 API，合并逻辑简单
**成本：** 2-3x API 调用成本

### 1.3 两阶段分析

**问题：** 单次 VL 调用要同时理解整体结构和精确读取标注值，任务负载过重。

**方案：**
- **Pass 1（全局）：** 整体结构（零件类型、阶梯数、孔数、整体形状）
- **Pass 2（局部）：** 裁剪标注区域，精确读取每个尺寸值

**预估提升：** 中 — 减少"大局对、细节错"
**复杂度：** 中等 — 需要图像裁剪 + 两次 VL 调用

### 1.4 结构化输出约束

**方案：** 用 function calling / JSON schema 强制 VL 输出固定结构，
而非自由文本后正则解析。

**预估提升：** 低-中 — 减少格式解析层的错误
**复杂度：** 低

### 1.5 Self-consistency

**方案：** 同模型同 prompt 跑 3-5 次，取众数。值不一致的维度标为低置信度。

**预估提升：** 中 — 对模型不确定的值提供置信度信号
**复杂度：** 低 — 只是多次调用 + 聚合

---

## Stage 1.5：策略选择 + 示例检索

### 1.5.1 扩充知识库

**问题：** 当前知识库只有少量旋转体示例，对板材、壳体、铸件等类型覆盖不足。

**方案：**
1. 每个 PartType 补充 5-10 个 TaggedExample
2. 每个示例覆盖不同的 feature 组合（bore+fillet、hole_pattern+chamfer 等）
3. 示例代码必须经过 CadQuery 执行验证（生成有效 STEP）
4. 多样化 CadQuery 构造方法（revolve、extrude、sweep、loft）

**目标覆盖矩阵：**

| PartType | 当前示例数 | 目标 | 构造方法 |
|----------|----------|------|---------|
| ROTATIONAL | ~3 | 8 | revolve, extrude+circular |
| ROTATIONAL_STEPPED | ~3 | 8 | revolve（多层）|
| PLATE | 0-1 | 6 | extrude |
| BRACKET | 0-1 | 6 | extrude+cut |
| SHELL | 0 | 5 | shell+cut |
| HOUSING | 0 | 5 | extrude+shell |

**预估提升：** 高 — 代码生成质量的基础
**复杂度：** 中 — 需要人工编写并验证

### 1.5.2 向量检索替代 Jaccard

**方案：** 用 embedding 模型编码 DrawingSpec 描述文本，做语义相似度检索。

**预估提升：** 中 — 比关键词 Jaccard 更鲁棒
**复杂度：** 中 — 需要 embedding 模型 + 向量存储

### 1.5.3 参数化代码模板

**问题：** Coder 从零生成代码容易犯结构性错误（方法调用顺序错、API 误用）。

**方案：** 对常见零件类型提供"骨架模板"，Coder 只需填参数：

```python
# 模板：rotational_stepped
import cadquery as cq

# --- 参数（由 Coder 填充）---
layers = [
    {"diameter": ${d1}, "height": ${h1}},
    {"diameter": ${d2}, "height": ${h2}},
]
bore_diameter = ${bore_d}  # None if no bore

# --- 固定结构 ---
result = cq.Workplane("XY")
for layer in layers:
    result = result.circle(layer["diameter"] / 2).extrude(layer["height"])
    result = result.faces(">Z").workplane()

if bore_diameter:
    result = result.faces("<Z").workplane().hole(bore_diameter)

cq.exporters.export(result, "${output_filename}")
```

**预估提升：** 高 — 消除结构性错误
**复杂度：** 中高 — 需为每种类型编写 + 验证模板

---

## Stage 2：代码生成

### 2.1 多路生成 + 择优（Best-of-N）

**问题：** 单次代码生成正确率有限。即使正确率为 60%，也意味着 40% 需要修复。

**方案：**
1. 生成 N 份代码（N=3-5），temperature 稍高以增加多样性
2. 全部执行，收集每份的几何验证结果
3. 按综合得分择优：

```python
def score_candidate(geo: GeometryResult, spec: DrawingSpec) -> float:
    """0-100 分，越高越好"""
    if not geo.is_valid:
        return 0

    score = 50  # 基础分（能执行就 50 分）

    # 体积合理性（+20）
    expected_vol = estimate_volume(spec)
    if expected_vol > 0:
        vol_err = abs(geo.volume - expected_vol) / expected_vol
        score += max(0, 20 * (1 - vol_err))

    # 包围盒匹配（+20）
    bbox_result = validate_bounding_box(geo.bbox, spec.overall_dimensions)
    if bbox_result.passed:
        score += 20

    # 拓扑合理性（+10）
    # 面数、孔数等（需实现 1.5.1 后）

    return score
```

4. 取最高分的候选进入 SmartRefiner

**概率分析：**

| 单次正确率 | N=1 | N=3 | N=5 |
|-----------|-----|-----|-----|
| 40% | 40% | 78% | 92% |
| 60% | 60% | 94% | 99% |
| 80% | 80% | 99% | 99.9% |

**预估提升：** 高 — 概率上最直接的改善
**复杂度：** 低-中 — 并行执行 + 打分逻辑
**成本：** N × Coder 调用成本

### 2.2 CadQuery API 白名单约束

**方案：** 在 prompt 中明确禁用已知问题 API，提供推荐用法列表。

**预估提升：** 低-中
**复杂度：** 低

### 2.3 执行前静态检查

**方案：** AST 检查 export 语句、未定义变量、禁止 API 调用。

**预估提升：** 低 — 拦截明显的烂代码
**复杂度：** 低

---

## Stage 3.5：几何验证增强

### 3.5.1 体积估算

**问题：** 当前只检查包围盒，不检查体积合理性。比例对但实心/空心搞反了检测不到。

**方案：** 从 DrawingSpec 的 profile 估算理论体积：

```python
def estimate_volume(spec: DrawingSpec) -> float:
    """从 DrawingSpec 估算理论体积（mm³）。"""
    import math
    vol = 0.0

    # 旋转体：∑ π × (d/2)² × h
    for layer in spec.base_body.profile:
        vol += math.pi * (layer.diameter / 2) ** 2 * layer.height

    # 减去通孔
    if spec.base_body.bore and spec.base_body.bore.through:
        total_h = sum(l.height for l in spec.base_body.profile)
        vol -= math.pi * (spec.base_body.bore.diameter / 2) ** 2 * total_h

    return vol
```

与 `GeometryResult.volume` 比对，偏差 > 30% 则标记。

**预估提升：** 中 — 快速发现整体比例/实心空心错误
**复杂度：** 低 — 5-10 行代码

### 3.5.2 拓扑验证

**问题：** 包围盒和体积对了，但孔数、阶梯数、面数可能不对。

**方案：**
1. 统计 STEP 模型的圆柱面数（= 孔/轴数量的线索）
2. 统计平面数
3. 与 spec.features 的期望特征数比对

```python
def count_topology(step_filepath: str) -> dict:
    """统计 STEP 模型的拓扑信息。"""
    import cadquery as cq
    shape = cq.importers.importStep(step_filepath).val()

    faces = shape.Faces()
    cylindrical = sum(1 for f in faces if f.geomType() == "CYLINDER")
    planar = sum(1 for f in faces if f.geomType() == "PLANE")

    return {
        "total_faces": len(faces),
        "cylindrical_faces": cylindrical,
        "planar_faces": planar,
        "shells": len(shape.Shells()),
        "solids": len(shape.Solids()),
    }
```

**预估提升：** 中高 — 捕获结构性错误
**复杂度：** 中等

### 3.5.3 截面分析

**问题：** 旋转体的阶梯轮廓精确性无法仅凭包围盒判断。

**方案：** 在已知高度处切横截面，测量外径，与 spec 的 profile 比对。

**预估提升：** 中 — 精准验证旋转体轮廓
**复杂度：** 中等

---

## Stage 4：SmartRefiner 增强

### 4.1 多视角渲染

**问题：** 当前只从单一角度渲染 3D 模型，VL 看不到被遮挡的特征。

**方案：**
1. 从 4 个标准视角渲染（正面、俯视、侧面、等轴测）
2. VL 同时接收所有视图 + 原始图纸
3. 修改 `_COMPARE_PROMPT` 提示 VL 逐视图对比

**渲染配置：**

```python
RENDER_VIEWS = [
    {"name": "front",   "direction": (0, -1, 0), "up": (0, 0, 1)},
    {"name": "top",     "direction": (0, 0, -1), "up": (0, 1, 0)},
    {"name": "right",   "direction": (1, 0, 0),  "up": (0, 0, 1)},
    {"name": "iso",     "direction": (1, -1, 1), "up": (0, 0, 1)},
]
```

**预估提升：** 高 — 消除单角度盲区
**复杂度：** 低-中 — 修改 render 函数 + VL prompt

### 4.2 回滚机制

**问题：** 某些修复反而让几何变更差（体积偏差增大、包围盒偏离），但管道不检测退化。

**方案：**

```python
# 在 pipeline.py 的 refinement 循环中
prev_score = compute_geometry_score(output_filepath, spec)

# ... refine + execute ...

new_score = compute_geometry_score(output_filepath, spec)
if new_score < prev_score * 0.9:  # 退化超过 10%
    logger.warning("Refinement degraded geometry, rolling back")
    restore_code(prev_code)
    execute(prev_code)  # 恢复到上一版本
```

**预估提升：** 中 — 防止越改越烂
**复杂度：** 低

### 4.3 结构化 VL 反馈

**方案：** 修改 VL prompt，要求输出 JSON 格式的 issues 列表：

```json
{
  "issues": [
    {
      "type": "missing_feature",
      "severity": "high",
      "description": "缺少 6 个螺栓孔",
      "expected": "6 holes on PCD 70",
      "location": "top face"
    }
  ]
}
```

**预估提升：** 中 — Coder 修复更精准
**复杂度：** 低

### 4.4 轮廓叠加比对

**方案：** 渲染 3D 模型的线框轮廓图，与原图纸叠加，VL 比对叠加图。

**预估提升：** 中高 — 直觉化差异定位
**复杂度：** 中等

---

## 跨阶段：系统性提升

### X.1 评测基准（前提条件）

参见 `2026-02-26-v2-p2-design.md` P2.1 章节。

**核心观点：** 没有评测基准，所有优化都是盲人摸象。这不是"提升质量"的手段，
但是衡量其他所有手段效果的前提。

### X.2 失败分类

**方案：** 对历史运行的失败 case 进行分类统计：

| 失败类型 | 表现 | 对应优化方向 |
|---------|------|------------|
| 类型识别错误 | part_type 判断错 | Stage 1 |
| 标注漏读 | 关键尺寸缺失/错误 | 1.1 OCR 辅助 |
| 代码执行失败 | CadQuery 语法/API 错误 | 2.1 多路生成 |
| 结构性错误 | 阶梯数/孔数不对 | 4.1 多视角 + 3.5.2 拓扑 |
| 尺寸偏差 | 数值不准但结构对 | 现有 Layer 1 诊断已覆盖 |

按频率排序后，优先攻坚最高频的失败类型。

---

## 优先级总览

### 第一梯队：立竿见影

| # | 方案 | 阶段 | 预估提升 | 复杂度 |
|---|------|------|---------|--------|
| 1 | 多路生成 + 择优 | Stage 2 | 高（概率提升最直接） | 低-中 |
| 2 | 多视角渲染 | Stage 4 | 高（消除单角度盲区） | 低-中 |
| 3 | 体积估算 | Stage 3.5 | 中（5 行代码可用） | 低 |

### 第二梯队：稳定提升

| # | 方案 | 阶段 | 预估提升 | 复杂度 |
|---|------|------|---------|--------|
| 4 | OCR 辅助标注提取 | Stage 1 | 高（标注漏读主因） | 中等 |
| 5 | 扩充知识库 | Stage 1.5 | 高（代码质量地基） | 中 |
| 6 | 回滚机制 | Stage 4 | 中（安全网） | 低 |
| 7 | 拓扑验证 | Stage 3.5 | 中高（结构性错误） | 中等 |

### 第三梯队：长线投资

| # | 方案 | 阶段 | 预估提升 | 复杂度 |
|---|------|------|---------|--------|
| 8 | 评测基准 | 跨阶段 | 前提条件 | 中 |
| 9 | 多模型投票 | Stage 1 | 中高（API 成本换质量） | 低 |
| 10 | 参数化模板 | Stage 1.5 | 高（消除结构性错误） | 中高 |

---

## 过拟合风险分析

> 2026-02-26 重构后评估

### 已消除的风险

SmartRefiner 已重构为零风险模式（`b074d26`）：Layer 1/2 不再提前返回跳过 VL。
这消除了"静态校验对测试用例过拟合 → 真实输入跳过 VL"的核心风险。

| 组件 | 重构前风险 | 重构后 |
|------|----------|--------|
| `validate_code_params` 名称匹配 | 高 — 直接跳过 VL | 已消除 — 仅诊断上下文 |
| `validate_bounding_box` best-axis | 高 — 直接跳过 VL | 已消除 — 仅诊断上下文 |
| 知识库 × 测试同源 | 中 — 影响示例选择 | 不变 — 但这是覆盖不足，非过拟合 |

### 残留问题：知识库覆盖不足

严格说这不是"过拟合"（模型在训练集上表现好、测试集上差），
而是"覆盖不足"（对未见过的零件类型缺少参考示例）。

解决方案：方案 1.5.1（扩充知识库）。
