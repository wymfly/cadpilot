"""Few-shot examples for gear parts.

The tooth profile is a simplified rectangular-slot approximation — sufficient
for structural modelling and as a code-generation template.  True involute
profiles require the ``cq-gears`` library or manual point computation.
"""

from ._base import TaggedExample

GEAR_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="标准直齿轮：m=2，z=24，b=20，中心孔φ16，键槽5×3",
        code="""\
import cadquery as cq
import math

# 齿轮参数
module, num_teeth, face_width = 2, 24, 20
bore_d = 16
key_w, key_d = 5, 3  # 键宽, 键槽深（从内孔向外）

# 基本圆尺寸
rp = module * num_teeth / 2      # 分度圆半径 = 24
ra = rp + module                  # 齿顶圆半径 = 26
rf = rp - 1.25 * module           # 齿根圆半径 = 21.5
gap_w = math.pi * module / 2      # 标准齿槽宽 ≈ π×m/2
gap_depth = (ra - rf) * 2 + 2    # 切槽径向深度（足够穿过齿高）

# 1. 齿顶圆柱（基体）
result = cq.Workplane("XY").circle(ra).extrude(face_width)

# 2. 切除齿槽（简化：矩形槽沿分度圆均布）
for i in range(num_teeth):
    angle = (i + 0.5) * 360.0 / num_teeth  # 槽中心角（错开半齿距）
    result = (result.faces(">Z").workplane()
        .transformed(rotate=(0, 0, angle))
        .center(rp, 0)
        .rect(gap_depth, gap_w)
        .cutBlind(face_width + 1))

# 3. 中心孔
result = result.faces(">Z").workplane().hole(bore_d)

# 4. 键槽（从内孔壁向外切，宽 key_w，深 key_d）
key_slot = (cq.Workplane("XY")
    .center(0, bore_d / 2 + key_d / 2)
    .rect(key_w, key_d)
    .extrude(face_width + 1))
result = result.cut(key_slot)

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"gear_teeth", "revolve", "bore", "keyway"}),
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
