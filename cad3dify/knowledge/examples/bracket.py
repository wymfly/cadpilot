"""Few-shot examples for bracket parts."""

from ._base import TaggedExample

BRACKET_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="L 形支架：底板100x80x10，立板80x60x10，底板4孔，立板2孔",
        code="""\
import cadquery as cq

# 底板
base_l, base_w, base_t = 100, 80, 10
# 立板
wall_h, wall_t = 60, 10

# L 形截面 extrude
pts = [
    (0, 0), (base_l, 0), (base_l, base_t),
    (wall_t, base_t), (wall_t, base_t + wall_h), (0, base_t + wall_h),
]
result = cq.Workplane("XZ").polyline(pts).close().extrude(base_w)

# 底板安装孔
result = (result.faces("<Z").workplane()
    .rect(base_l - 20, base_w - 20, forConstruction=True)
    .vertices().hole(10))

# 立板安装孔
result = (result.faces("<X").workplane()
    .center(0, wall_h/2 + base_t/2)
    .rect(base_w - 30, wall_h - 20, forConstruction=True)
    .vertices().hole(8))

# 内角圆角
try:
    result = result.edges(cq.selectors.NearestToPointSelector((wall_t/2, base_w/2, base_t))).fillet(5)
except Exception:
    pass

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "hole_pattern", "fillet"}),
    ),
    TaggedExample(
        description="U形槽架：总宽100，通道高60，深70，壁厚10，底部4×φ8安装孔",
        code="""\
import cadquery as cq

# U 形截面参数
outer_w, channel_h, depth = 100, 60, 70
wall_t = 10

# U 形截面（在 XZ 平面绘制：X 为宽，Z 为高）
pts = [
    (0, 0),
    (outer_w, 0),
    (outer_w, channel_h),
    (outer_w - wall_t, channel_h),
    (outer_w - wall_t, wall_t),
    (wall_t, wall_t),
    (wall_t, channel_h),
    (0, channel_h),
]
result = cq.Workplane("XZ").polyline(pts).close().extrude(depth)

# 底部安装孔（4角均布）
result = (result.faces("<Z").workplane()
    .rect(outer_w - 20, depth - 20, forConstruction=True)
    .vertices().hole(8))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "slot", "hole_pattern"}),
    ),
    TaggedExample(
        description="T形腹板支架：底板150x60x10，中央立筋高80厚10，底板4×M10安装孔",
        code="""\
import cadquery as cq

# 底板参数
base_l, base_w, base_t = 150, 60, 10
# 立筋参数
rib_h, rib_t = 80, 10

# 底板
result = cq.Workplane("XY").box(base_l, base_w, base_t)

# 中央立筋（从底板顶面向上生长）
result = (result.faces(">Z").workplane()
    .center(0, 0)
    .rect(rib_t, base_w)
    .extrude(rib_h))

# 底板安装孔（4角）
result = (result.faces("<Z").workplane()
    .rect(base_l - 20, base_w - 20, forConstruction=True)
    .vertices().hole(10))

# 底板-立筋接合处圆角
try:
    result = result.edges(
        cq.selectors.NearestToPointSelector((0, 0, base_t / 2))
    ).fillet(5)
except Exception:
    pass

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "hole_pattern", "fillet"}),
    ),
]
