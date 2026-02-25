BRACKET_EXAMPLES: list[tuple[str, str]] = [
    (
        "L 形支架：底板100x80x10，立板80x60x10，底板4孔，立板2孔",
        '''\
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
''',
    ),
]
