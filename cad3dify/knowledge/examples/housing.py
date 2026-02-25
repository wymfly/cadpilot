"""Few-shot examples for housing/enclosure parts."""

from ._base import TaggedExample

HOUSING_EXAMPLES: list[TaggedExample] = [
    TaggedExample(
        description="矩形箱体：120x80x60，壁厚3，顶面开口，四角安装凸台",
        code="""\
import cadquery as cq

length, width, height = 120, 80, 60
wall_t = 3
boss_d, boss_h = 12, 5

# 箱体 + 抽壳
result = (cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").shell(-wall_t))

# 底部安装凸台
result = (result.faces("<Z").workplane(invert=True)
    .rect(length - 15, width - 15, forConstruction=True)
    .vertices()
    .circle(boss_d/2).extrude(boss_h)
    .faces("<Z").workplane(invert=True)
    .rect(length - 15, width - 15, forConstruction=True)
    .vertices()
    .hole(5))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "shell", "boss", "hole_pattern"}),
    ),
    TaggedExample(
        description="圆柱壳体：外径φ100，高80，壁厚4，顶面开口，底部4个安装凸台",
        code="""\
import cadquery as cq

d_outer, height = 100, 80
wall_t = 4
boss_d, boss_h = 14, 5
n_boss, pcd = 4, 70  # 凸台分布圆径
boss_hole_d = 8

# 圆柱 + 抽壳（顶面开口）
result = cq.Workplane("XY").circle(d_outer / 2).extrude(height)
result = result.faces(">Z").shell(-wall_t)

# 底部安装凸台
result = (result.faces("<Z").workplane(invert=True)
    .polarArray(pcd / 2, 0, 360, n_boss)
    .circle(boss_d / 2).extrude(boss_h))

# 安装螺孔
result = (result.faces("<Z").workplane(invert=True)
    .polarArray(pcd / 2, 0, 360, n_boss)
    .hole(boss_hole_d))

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"revolve", "shell", "boss", "hole_pattern"}),
    ),
    TaggedExample(
        description="控制器外壳：120x80x40，壁厚2，顶面开口，底部4个M3内侧安装柱",
        code="""\
import cadquery as cq

length, width, height = 120, 80, 40
wall_t = 2
standoff_h, standoff_od = 6, 6
standoff_hole_d = 3.2  # M3 过孔
margin = 8

# 开口箱体
result = (cq.Workplane("XY")
    .box(length, width, height)
    .faces(">Z").shell(-wall_t))

# 内侧安装柱（从内底面向上生长）
inner_z = -height / 2 + wall_t  # 内底面 Z 坐标
for sx, sy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
    cx = sx * (length / 2 - margin)
    cy = sy * (width / 2 - margin)
    boss = (cq.Workplane("XY")
        .workplane(offset=inner_z)
        .center(cx, cy)
        .circle(standoff_od / 2)
        .extrude(standoff_h))
    result = result.union(boss)
    # 安装螺孔（从外底面穿入）
    hole = (cq.Workplane("XY")
        .workplane(offset=-height / 2)
        .center(cx, cy)
        .circle(standoff_hole_d / 2)
        .extrude(wall_t + standoff_h + 1))
    result = result.cut(hole)

cq.exporters.export(result, "${output_filename}")
""",
        features=frozenset({"extrude", "shell", "boss", "hole_pattern"}),
    ),
]
