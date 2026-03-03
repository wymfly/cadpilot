"""Mesh diagnosis — analyze defects and grade severity."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import trimesh


DefectLevel = Literal["clean", "mild", "moderate", "severe"]


@dataclass
class MeshDiagnosis:
    """Result of mesh defect analysis."""

    level: DefectLevel
    issues: list[str] = field(default_factory=list)


def diagnose(mesh: trimesh.Trimesh) -> MeshDiagnosis:
    """Analyze mesh topology defects, return severity grade.

    Levels:
    - clean: watertight + oriented, no issues
    - mild: normals/winding problems only
    - moderate: holes or non-manifold edges
    - severe: self-intersection or large missing areas
    """
    issues: list[str] = []

    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return MeshDiagnosis(level="severe", issues=["empty mesh"])

    is_wt = mesh.is_watertight

    # Check face orientation consistency.
    # Strategy: copy the mesh, run fix_normals (which fixes both winding
    # consistency AND outward orientation), and compare faces.
    # If faces changed, the original had orientation issues — either
    # inconsistent winding or inward-facing normals (negative volume).
    try:
        test_mesh = mesh.copy()
        original_faces = mesh.faces.copy()
        trimesh.repair.fix_normals(test_mesh)
        oriented = np.array_equal(original_faces, test_mesh.faces)
    except Exception:
        oriented = False

    if is_wt and oriented:
        return MeshDiagnosis(level="clean", issues=[])

    # Check normals consistency
    if not oriented:
        issues.append("inconsistent face orientation")

    # Non-watertight → has holes or non-manifold geometry
    if not is_wt:
        # Count boundary/non-manifold edges using numpy (fast for large meshes)
        unique_edges, counts = np.unique(
            mesh.edges_sorted, axis=0, return_counts=True
        )
        boundary_count = int(np.sum(counts == 1))
        non_manifold_count = int(np.sum(counts > 2))

        if non_manifold_count > 0:
            issues.append(f"{non_manifold_count} non-manifold edges")
        if boundary_count > 0:
            issues.append(f"{boundary_count} boundary edges (holes)")

        # Severe heuristics:
        # 1. High ratio of non-manifold edges → likely self-intersection
        # 2. Missing face ratio: compare actual faces to expected for a
        #    closed surface (Euler formula: V - E + F = 2 for genus-0).
        #    Large deviation suggests large missing areas.
        expected_faces = 2 * len(mesh.vertices) - 4  # genus-0 estimate
        if expected_faces > 0:
            missing_ratio = max(0, 1 - len(mesh.faces) / expected_faces)
        else:
            missing_ratio = 0.0

        if non_manifold_count > len(mesh.edges_unique) * 0.1:
            issues.append(
                f"high non-manifold ratio ({non_manifold_count} edges, possible self-intersection)"
            )
            return MeshDiagnosis(level="severe", issues=issues)

        if missing_ratio > 0.3:
            issues.append(f"missing face ratio {missing_ratio:.1%}")
            return MeshDiagnosis(level="severe", issues=issues)

        return MeshDiagnosis(level="moderate", issues=issues)

    # Watertight but not well-oriented
    return MeshDiagnosis(level="mild", issues=issues)


def validate_repair(mesh: trimesh.Trimesh) -> bool:
    """Check if repaired mesh meets watertight standard.

    Criteria:
    - mesh.is_watertight == True
    - volume > 0
    - has faces (no degenerate mesh)
    - no degenerate faces (zero-area triangles)
    """
    if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
        return False
    if not mesh.is_watertight:
        return False
    try:
        vol = mesh.volume
        if vol <= 0:
            return False
    except Exception:
        return False
    # Check for degenerate faces (zero-area triangles)
    try:
        areas = mesh.area_faces
        if (areas < 1e-10).any():
            return False
    except Exception:
        return False
    return True
