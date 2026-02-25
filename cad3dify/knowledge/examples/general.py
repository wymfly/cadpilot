"""Few-shot examples for general / miscellaneous parts."""

from ._base import TaggedExample

GENERAL_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="空心管件：外径φ60，内径φ50，长200，两端倒角C1",
        code="""\
import cadquery as cq

# 管件参数
d_outer, d_inner = 60, 50
length = 200
chamfer = 1

r_outer, r_inner = d_outer / 2, d_inner / 2

# 薄壁轮廓
profile_pts = [
    (r_inner, 0),
    (r_outer, 0),
    (r_outer, length),
    (r_inner, length),
]
result = (cq.Workplane("XZ").polyline(profile_pts).close()
    .revolve(360, (0, 0, 0), (0, 1, 0)))

# 两端倒角
try:
    result = result.edges("<Y").chamfer(chamfer)
    result = result.edges(">Y").chamfer(chamfer)
except Exception:
    pass

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"revolve", "bore", "chamfer"}),
    ),
    TaggedExample(
        description="矩形块体：100x80x40，顶面2×2排列4×φ8通孔，侧面2×φ6螺孔深15",
        code="""\
import cadquery as cq

length, width, height = 100, 80, 40
top_hole_d = 8
side_hole_d, side_hole_depth = 6, 15

result = cq.Workplane("XY").box(length, width, height)

# 顶面通孔（2×2均布）
result = (result.faces(">Z").workplane()
    .rect(length - 30, width - 30, forConstruction=True)
    .vertices().hole(top_hole_d))

# 侧面螺孔
result = (result.faces(">Y").workplane()
    .rect(length - 40, height - 20, forConstruction=True)
    .vertices().hole(side_hole_d, depth=side_hole_depth))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "hole_pattern"}),
    ),
    TaggedExample(
        description="带圆角倒角实体：60x50x30，竖棱R5圆角，顶面R3圆角，底面C1倒角",
        code="""\
import cadquery as cq

length, width, height = 60, 50, 30
vertical_fillet = 5
top_fillet = 3
bottom_chamfer = 1

result = cq.Workplane("XY").box(length, width, height)

# 竖向棱（四条竖边）圆角
try:
    result = result.edges("|Z").fillet(vertical_fillet)
except Exception:
    pass

# 顶面圆角
try:
    result = result.edges(">Z").fillet(top_fillet)
except Exception:
    pass

# 底面倒角
try:
    result = result.edges("<Z").chamfer(bottom_chamfer)
except Exception:
    pass

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "fillet", "chamfer"}),
    ),
]
