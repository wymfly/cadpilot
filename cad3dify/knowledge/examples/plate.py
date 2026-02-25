PLATE_EXAMPLES: list[tuple[str, str]] = [
    (
        "矩形安装板：200x150x10，四角4×φ12安装孔，中心φ60通孔",
        '''\
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
''',
    ),
]
