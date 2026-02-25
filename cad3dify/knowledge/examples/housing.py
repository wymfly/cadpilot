HOUSING_EXAMPLES: list[tuple[str, str]] = [
    (
        "矩形箱体：120x80x60，壁厚3，顶面开口，四角安装凸台",
        '''\
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
''',
    ),
]
