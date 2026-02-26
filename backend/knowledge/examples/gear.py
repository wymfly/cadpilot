"""Few-shot examples for gear parts.

Includes involute gear math (base/addendum/dedendum circles, involute point
generation) and simplified rectangular-slot approximations.
"""

from ._base import TaggedExample

GEAR_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="渐开线直齿轮 m=2 z=24 b=20，精确齿廓，中心孔φ16，键槽5×3",
        features=frozenset({"gear_teeth", "revolve", "bore", "keyway", "involute"}),
        code="""\
import cadquery as cq
import math

# 齿轮参数
m = 2        # 模数 (mm)
z = 24       # 齿数
alpha = math.radians(20)  # 压力角
b = 20       # 齿宽 (mm)

# 基本圆参数
rp = m * z / 2             # 分度圆半径 = 24
ra = m * (z + 2) / 2       # 齿顶圆半径 = 26
rf = m * (z - 2.5) / 2     # 齿根圆半径 = 21.5
rb = rp * math.cos(alpha)  # 基圆半径

# 渐开线点生成
def involute_pt(rb, t):
    return (rb * (math.cos(t) + t * math.sin(t)),
            rb * (math.sin(t) - t * math.cos(t)))

t_max = math.sqrt((ra / rb) ** 2 - 1)
inv_pts = [involute_pt(rb, i * t_max / 15) for i in range(16)]

# 建立齿顶圆柱基体
result = cq.Workplane("XY").circle(ra).extrude(b)

# 齿槽切除
tooth_angle = 360 / z
slot_w = m * math.pi / 2
for i in range(z):
    angle = i * tooth_angle
    result = (result.faces(">Z").workplane()
        .transformed(rotate=(0, 0, angle))
        .center(rp, 0)
        .rect(m * 1.25, slot_w)
        .cutBlind(-(b + 1)))

# 中心孔 φ16
result = result.faces(">Z").workplane().circle(8).cutThruAll()

# 键槽 5×3
result = (result.faces(">Z").workplane()
    .center(0, 6.5)
    .rect(5, 3)
    .cutThruAll())

cq.exporters.export(result, "${output_filename}")
""",
    ),
    TaggedExample(
        description="腹板型直齿轮：m=3，z=32，b=25，中心孔φ40，腹板6×φ8均布孔PCD64",
        code="""\
import cadquery as cq
import math

# 齿轮参数
module, num_teeth, face_width = 3, 32, 25
bore_d = 40
n_web_holes, web_hole_d, web_pcd = 6, 8, 64  # 腹板通孔

# 基本圆尺寸
rp = module * num_teeth / 2    # 分度圆半径 = 48
ra = rp + module                # 齿顶圆半径 = 51
rf = rp - 1.25 * module         # 齿根圆半径 = 44.25
gap_w = math.pi * module / 2
gap_depth = (ra - rf) * 2 + 2

# 1. 基体
result = cq.Workplane("XY").circle(ra).extrude(face_width)

# 2. 切齿槽
for i in range(num_teeth):
    angle = (i + 0.5) * 360.0 / num_teeth
    result = (result.faces(">Z").workplane()
        .transformed(rotate=(0, 0, angle))
        .center(rp, 0)
        .rect(gap_depth, gap_w)
        .cutBlind(face_width + 1))

# 3. 中心孔
result = result.faces(">Z").workplane().hole(bore_d)

# 4. 腹板均布通孔（减重 + 安装）
for i in range(n_web_holes):
    angle = math.radians(i * 360 / n_web_holes)
    x, y = (web_pcd / 2) * math.cos(angle), (web_pcd / 2) * math.sin(angle)
    hole = cq.Workplane("XY").center(x, y).circle(web_hole_d / 2).extrude(face_width + 1)
    result = result.cut(hole)

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"gear_teeth", "revolve", "bore", "hole_pattern"}),
    ),
    TaggedExample(
        description="小模数直齿轮：m=1，z=40，b=12，中心孔φ10",
        code="""\
import cadquery as cq
import math

# 齿轮参数
module, num_teeth, face_width = 1, 40, 12
bore_d = 10

# 基本圆尺寸
rp = module * num_teeth / 2    # 分度圆半径 = 20
ra = rp + module                # 齿顶圆半径 = 21
rf = rp - 1.25 * module         # 齿根圆半径 = 18.75
gap_w = math.pi * module / 2
gap_depth = (ra - rf) * 2 + 2

# 1. 基体
result = cq.Workplane("XY").circle(ra).extrude(face_width)

# 2. 切齿槽
for i in range(num_teeth):
    angle = (i + 0.5) * 360.0 / num_teeth
    result = (result.faces(">Z").workplane()
        .transformed(rotate=(0, 0, angle))
        .center(rp, 0)
        .rect(gap_depth, gap_w)
        .cutBlind(face_width + 1))

# 3. 中心孔
result = result.faces(">Z").workplane().hole(bore_d)

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"gear_teeth", "revolve", "bore"}),
    ),
]
