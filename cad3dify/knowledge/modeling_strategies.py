from .part_types import PartType

# 每种零件类型的 CadQuery 建模策略指南
STRATEGIES: dict[PartType, str] = {
    PartType.ROTATIONAL: """\
## 旋转体零件建模策略

### 基体构建：使用 revolve（旋转）
- 在 XZ 平面绘制半截面轮廓（polyline），然后 revolve(360°)
- 轮廓点按 (radius, height) 从内孔底部开始，逆时针排列
- 结束时 close() 自动闭合轮廓

### CadQuery 代码模式
```python
profile_pts = [
    (r_bore, 0),      # 内孔底部
    (r_outer, 0),     # 外缘底部
    (r_outer, height), # 外缘顶部
    (r_bore, height),  # 内孔顶部
]
result = cq.Workplane("XZ").polyline(profile_pts).close().revolve(360, (0,0,0), (0,1,0))
```

### 特征添加顺序（严格遵守）
1. revolve 基体
2. fillet 圆角（在 cut 之前！否则边被破坏）
3. cut 孔特征

### 圆角选择器
- 使用 NearestToPointSelector 精确选择边：
```python
result.edges(cq.selectors.NearestToPointSelector((x, y, z))).fillet(r)
```
- 不要用 >Z / <Z 等方向选择器，对复杂几何不可靠

### 螺栓孔阵列
```python
import math
for i in range(n_bolts):
    angle = math.radians(i * 360 / n_bolts)
    x = (pcd / 2) * math.cos(angle)
    y = (pcd / 2) * math.sin(angle)
    hole = cq.Workplane("XY").center(x, y).circle(d_bolt / 2).extrude(thickness + 1)
    result = result.cut(hole)
```

### 常见陷阱
- 绝对不要用多个圆柱 union 再 fillet，会导致圆角操作失败
- revolve 一次成型的单一实体，fillet 成功率极高
- fillet 用 try/except 包裹，某些边可能因几何原因无法倒角
""",

    PartType.ROTATIONAL_STEPPED: """\
## 阶梯旋转体建模策略

### 基体构建：revolve profile 一次成型
- 在 XZ 平面绘制包含所有阶梯的半截面轮廓
- 每个阶梯对应轮廓中的一段水平+垂直线
- revolve 360° 一次生成完整阶梯结构

### CadQuery 代码模式（关键！）
```python
# 半截面轮廓点 (radius, height)，从内孔底部开始逆时针
profile_pts = [
    (r_bore, 0),                          # 内孔底部
    (r_base, 0),                          # 最大直径底面
    (r_base, h_base),                     # 最大直径顶面
    (r_mid, h_base),                      # 中间阶梯底面
    (r_mid, h_base + h_mid),              # 中间阶梯顶面
    (r_top, h_base + h_mid),              # 顶部阶梯底面
    (r_top, h_base + h_mid + h_top),      # 顶部阶梯顶面
    (r_bore, h_base + h_mid + h_top),     # 内孔顶部
]
result = cq.Workplane("XZ").polyline(profile_pts).close().revolve(360, (0,0,0), (0,1,0))
```

### 阶梯过渡圆角
- 每个阶梯交界处有 2 条环形边需要圆角
- 用 NearestToPointSelector 逐一选择：
```python
# 外径->小径的水平拐角
result = result.edges(cq.selectors.NearestToPointSelector((r_large, 0, z_transition))).fillet(r)
# 小径->内侧的垂直拐角
result = result.edges(cq.selectors.NearestToPointSelector((r_small, 0, z_transition))).fillet(r)
```

### 关键原则
1. 所有阶梯在一个 revolve profile 中完成——不要分段建模
2. fillet 在 cut（螺栓孔）之前
3. 螺栓孔穿过法兰部分，extrude 高度 > 法兰厚度
4. 每个 fillet 用 try/except 包裹
""",

    PartType.PLATE: """\
## 板件建模策略

### 基体构建：sketch + extrude
- 在 XY 平面绘制轮廓，extrude 到板厚
- 复杂轮廓用 polyline + close + extrude
- 简单矩形用 box

### CadQuery 代码模式
```python
# 矩形板
result = cq.Workplane("XY").box(length, width, thickness)

# 异形板
pts = [(0,0), (100,0), (100,50), (80,50), (80,20), (0,20)]
result = cq.Workplane("XY").polyline(pts).close().extrude(thickness)
```

### 特征添加
1. 孔位：faces(">Z").workplane().pushPoints(pts).hole(d)
2. 沉头孔：cboreHole(hole_d, cbore_d, cbore_depth)
3. 槽：faces(">Z").workplane().slot2D(length, width).cutBlind(-depth)
4. 圆角：edges("|Z").fillet(r) 选择垂直边
""",

    PartType.BRACKET: """\
## 支架/角件建模策略

### 基体构建：分部件 union
- 分解为底板 + 立板（+ 可选加强筋）
- 各部分独立 extrude 后 union
- 或使用 L 形轮廓一次 extrude

### CadQuery 代码模式
```python
# L 形支架
base = cq.Workplane("XY").box(base_l, base_w, base_t)
wall = (cq.Workplane("XY")
    .workplane(offset=base_t)
    .center(-base_l/2 + wall_t/2, 0)
    .box(wall_t, base_w, wall_h))
result = base.union(wall)

# 加强筋（三角形）
rib_pts = [(0,0), (rib_l, 0), (0, rib_h)]
rib = (cq.Workplane("XZ")
    .center(-base_l/2, base_t)
    .polyline(rib_pts).close()
    .extrude(rib_t))
result = result.union(rib)
```

### 连接处圆角
- union 后在连接边做 fillet
- 选择内角边：edges 用 NearestToPointSelector
""",

    PartType.HOUSING: """\
## 箱体/壳体建模策略

### 基体构建：extrude + shell 抽壳
- 先建实体外形
- 用 shell 命令抽壳（指定保留面）

### CadQuery 代码模式
```python
# 矩形箱体
result = (cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z")  # 顶面开口
    .shell(-wall_thickness))  # 负值=向内抽壳

# 带安装凸台
result = (result
    .faces("<Z").workplane(invert=True)
    .rect(bolt_spacing_x, bolt_spacing_y, forConstruction=True)
    .vertices()
    .circle(boss_d/2).extrude(boss_h))
```
""",

    PartType.GEAR: """\
## 齿轮建模策略

### 基体构建：参数曲线 + twistExtrude
- 用参数方程生成齿形轮廓
- twistExtrude 创建螺旋齿

### CadQuery 代码模式
```python
from math import sin, cos, pi, floor

def gear_profile(t, r1, r2):
    # 外摆线和内摆线组合
    ...

result = (cq.Workplane("XY")
    .parametricCurve(lambda t: gear_profile(t * 2 * pi, module, teeth))
    .twistExtrude(face_width, helix_angle)
    .faces(">Z").workplane().circle(bore_d/2).cutThruAll())
```
""",

    PartType.GENERAL: """\
## 通用建模策略

### 分析步骤
1. 识别基体形状（最大的连续实体）
2. 确定基体构建方式（extrude/revolve/loft）
3. 按从大到小的顺序添加特征
4. 圆角/倒角最后做

### CadQuery 基本原则
- 选择合适的初始 Workplane（XY/XZ/YZ）
- 所有尺寸参数化（用变量不用硬编码数字）
- 布尔操作后检查 val().isValid()
- fillet/chamfer 在所有 cut 操作之前
- 导出用 cq.exporters.export(result, filepath)
""",
}


def get_strategy(part_type: PartType) -> str:
    """获取零件类型对应的建模策略"""
    return STRATEGIES.get(part_type, STRATEGIES[PartType.GENERAL])
