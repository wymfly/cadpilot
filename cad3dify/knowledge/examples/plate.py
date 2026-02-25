"""Few-shot examples for plate parts."""

from ._base import TaggedExample

PLATE_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="矩形安装板：200x150x10，四角4×φ12安装孔，中心φ60通孔",
        code="""\
import cadquery as cq

length, width, thickness = 200, 150, 10
hole_d, center_hole_d = 12, 60
margin = 20

result = (cq.Workplane("XY")
    .box(length, width, thickness)
    .faces(">Z").workplane()
    .hole(center_hole_d)
    .faces(">Z").workplane()
    .rect(length - 2*margin, width - 2*margin, forConstruction=True)
    .vertices()
    .hole(hole_d))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "hole_pattern", "bore"}),
    ),
    TaggedExample(
        description="圆形法兰板：φ160，厚12，中心孔φ40，6×φ12螺栓孔PCD110，外缘R3圆角",
        code="""\
import cadquery as cq
import math

d_flange, thickness = 160, 12
d_bore = 40
n_bolts, d_bolt, pcd = 6, 12, 110
fillet_r = 3

result = cq.Workplane("XY").circle(d_flange / 2).extrude(thickness)
result = result.faces(">Z").workplane().hole(d_bore)

# 均布螺栓孔
for i in range(n_bolts):
    angle = math.radians(i * 360 / n_bolts)
    x, y = (pcd / 2) * math.cos(angle), (pcd / 2) * math.sin(angle)
    hole = cq.Workplane("XY").center(x, y).circle(d_bolt / 2).extrude(thickness + 1)
    result = result.cut(hole)

# 外缘圆角
try:
    result = result.edges(">Z").fillet(fillet_r)
except Exception:
    pass

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "hole_pattern", "bore", "fillet"}),
    ),
    TaggedExample(
        description="T形槽工作台板：300x150x25，3条纵向T形槽（槽口12×8，槽底20×12）",
        code="""\
import cadquery as cq

length, width, thickness = 300, 150, 25
slot_top_w, slot_top_d = 12, 8    # 槽口：宽×深
slot_bot_w, slot_bot_d = 20, 12   # 槽底：宽×深（继续向下）

result = cq.Workplane("XY").box(length, width, thickness)

# 3条纵向T形槽，Y方向均布
for y in [-width / 4, 0, width / 4]:
    # 上部窄槽
    result = (result.faces(">Z").workplane()
        .center(0, y)
        .rect(length + 1, slot_top_w)
        .cutBlind(slot_top_d))
    # 下部扩宽槽（从窄槽底部继续切）
    result = (result.faces(">Z").workplane(offset=-slot_top_d)
        .center(0, y)
        .rect(length + 1, slot_bot_w)
        .cutBlind(slot_bot_d))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "slot"}),
    ),
    TaggedExample(
        description="带加强筋底板：200x150x8，3条纵向筋高20厚6，四角M10安装孔",
        code="""\
import cadquery as cq

length, width, plate_t = 200, 150, 8
rib_h, rib_t = 20, 6
hole_d, margin = 10, 15

# 底板
result = cq.Workplane("XY").box(length, width, plate_t)

# 纵向加强筋（从底板上表面向上生长）
for x in [-length / 4, 0, length / 4]:
    result = (result.faces(">Z").workplane()
        .center(x, 0)
        .rect(rib_t, width)
        .extrude(rib_h))

# 安装孔（底面四角）
result = (result.faces("<Z").workplane()
    .rect(length - 2 * margin, width - 2 * margin, forConstruction=True)
    .vertices().hole(hole_d))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "rib", "hole_pattern"}),
    ),
]
