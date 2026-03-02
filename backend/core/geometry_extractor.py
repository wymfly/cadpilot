"""Geometry information extractor for printability analysis.

Provides two paths:
- STEP files: CadQuery/OCP bounding box + volume extraction
- Mesh files: trimesh bounding box + volume + overhang estimation

Both return a standardized geometry_info dict consumed by PrintabilityChecker.
Note: min_wall_thickness and min_hole_diameter are not yet implemented
and always return None.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_geometry_from_step(
    step_path: str, *, run_vertex_analysis: bool = True,
) -> dict[str, Any]:
    """Extract geometry_info from a STEP file using CadQuery/OCP.

    When *run_vertex_analysis* is True, converts STEP to a temporary mesh
    and runs VertexAnalyzer for accurate ``min_wall_thickness`` and
    ``max_overhang_angle``.

    Returns dict with keys:
        bounding_box: {x, y, z} in mm
        min_wall_thickness: float in mm (may be None if analysis fails)
        max_overhang_angle: float in degrees (may be None)
        volume_cm3: float
        min_hole_diameter: float in mm (may be None)
    """
    import cadquery as cq  # noqa: E402 — lazy-loaded heavy dependency

    wp = cq.importers.importStep(step_path)
    shape = wp.val()
    bb = shape.BoundingBox()
    volume_mm3 = shape.Volume()

    geometry_info: dict[str, Any] = {
        "bounding_box": {
            "x": round(bb.xlen, 2),
            "y": round(bb.ylen, 2),
            "z": round(bb.zlen, 2),
        },
        "volume_cm3": round(volume_mm3 / 1000.0, 4),
        "min_wall_thickness": None,
        "max_overhang_angle": None,
        "min_hole_diameter": None,
    }

    if run_vertex_analysis:
        stl_path = _step_to_temp_stl(step_path)
        if stl_path:
            _try_vertex_analysis(stl_path, geometry_info)

    return geometry_info


def _step_to_temp_stl(step_path: str) -> Optional[str]:
    """Convert STEP to a temporary STL file for mesh analysis."""
    try:
        from backend.core.format_exporter import FormatExporter

        exporter = FormatExporter()
        return exporter._step_to_stl_temp(step_path, exporter._default_config())
    except Exception as exc:
        logger.warning("STEP → STL conversion failed: %s", exc)
        return None


def extract_geometry_from_mesh(
    mesh_path: str, *, run_vertex_analysis: bool = True,
) -> dict[str, Any]:
    """Extract geometry_info from a mesh file (GLB/STL) using trimesh.

    When *run_vertex_analysis* is True, runs VertexAnalyzer to fill accurate
    ``min_wall_thickness`` and ``max_overhang_angle``, and stores vertex-level
    data in ``_vertex_analysis`` for region computation by PrintabilityChecker.
    """
    import trimesh  # noqa: E402 — lazy-loaded heavy dependency

    mesh = trimesh.load(mesh_path)
    bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
    extents = bounds[1] - bounds[0]

    geometry_info: dict[str, Any] = {
        "bounding_box": {
            "x": round(float(extents[0]), 2),
            "y": round(float(extents[1]), 2),
            "z": round(float(extents[2]), 2),
        },
        "volume_cm3": (
            round(float(mesh.volume) / 1000.0, 4)
            if mesh.is_watertight
            else None
        ),
        "min_wall_thickness": None,
        "max_overhang_angle": _estimate_max_overhang(mesh),
        "min_hole_diameter": None,
    }

    if run_vertex_analysis:
        _try_vertex_analysis(mesh_path, geometry_info)

    return geometry_info


def _try_vertex_analysis(mesh_path: str, geometry_info: dict[str, Any]) -> None:
    """Run VertexAnalyzer and fill geometry_info with accurate measurements.

    On success, sets ``min_wall_thickness``, ``max_overhang_angle``, and
    ``_vertex_analysis`` (vertices + risk arrays for region computation).
    On failure, leaves geometry_info unchanged.
    """
    try:
        import numpy as np

        from backend.core.vertex_analyzer import VertexAnalyzer

        analyzer = VertexAnalyzer()
        result = analyzer.analyze(mesh_path)

        valid_wall = result.wall_thickness[
            result.wall_thickness < VertexAnalyzer.SENTINEL_THICKNESS
        ]
        if len(valid_wall) > 0:
            geometry_info["min_wall_thickness"] = round(float(np.min(valid_wall)), 3)

        geometry_info["max_overhang_angle"] = round(
            float(np.max(result.overhang_angle)), 1
        )

        # Store vertex-level data for region computation by PrintabilityChecker.
        # Mesh vertices + risk arrays let us compute centroid of at-risk vertices.
        import trimesh

        mesh = trimesh.load(mesh_path, force="mesh")
        geometry_info["_vertex_analysis"] = {
            "vertices": np.array(mesh.vertices),
            "risk_wall": result.risk_wall,
            "risk_overhang": result.risk_overhang,
            "wall_thickness": result.wall_thickness,
            "overhang_angle": result.overhang_angle,
        }
        logger.info("Vertex analysis enriched geometry_info for %s", mesh_path)
    except Exception as exc:
        logger.warning("Vertex analysis failed (non-fatal): %s", exc)


def _estimate_max_overhang(mesh: Any) -> Optional[float]:
    """Estimate max overhang angle from face normals."""
    try:
        import numpy as np

        normals = mesh.face_normals
        z_axis = np.array([0, 0, -1])
        cos_angles = np.dot(normals, z_axis)
        angles_deg = np.degrees(np.arccos(np.clip(cos_angles, -1, 1)))
        downward = angles_deg[angles_deg < 90]
        return round(float(np.max(downward)), 1) if len(downward) > 0 else 0.0
    except Exception:
        return None
