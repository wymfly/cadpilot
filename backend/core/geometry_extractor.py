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


def extract_geometry_from_step(step_path: str) -> dict[str, Any]:
    """Extract geometry_info from a STEP file using CadQuery/OCP.

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
    return geometry_info


def extract_geometry_from_mesh(mesh_path: str) -> dict[str, Any]:
    """Extract geometry_info from a mesh file (GLB/STL) using trimesh.

    min_wall_thickness is None for mesh files (computationally expensive).
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
    return geometry_info


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
