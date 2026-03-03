"""BasicOrientStrategy -- 6-direction discrete orientation search.

Evaluates +/-X, +/-Y, +/-Z orientations using a weighted scoring function:
  score = w_support * norm_support + w_height * norm_height + w_stability * instability
Lower score = better orientation.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import trimesh

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)

# 6 cardinal rotations: identity, +/-90 deg around X, +/-90 deg around Y, 180 deg around X
_CARDINAL_ROTATIONS = [
    ("Z-up (identity)", np.eye(4)),
    ("X-up (+90\u00b0 Y)", trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0])),
    ("X-down (-90\u00b0 Y)", trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0])),
    ("Y-up (-90\u00b0 X)", trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])),
    ("Y-down (+90\u00b0 X)", trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0])),
    ("Z-down (180\u00b0 X)", trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])),
]


class BasicOrientStrategy(NodeStrategy):
    """6-direction discrete orientation search."""

    def evaluate_orientation(self, mesh: trimesh.Trimesh, rotation: np.ndarray) -> float:
        """Evaluate a single orientation. Lower = better."""
        rotated = mesh.copy()
        rotated.apply_transform(rotation)

        extents = rotated.bounding_box.extents
        z_height = extents[2]

        # Estimate support area: sum of face areas where face normal Z < -cos(45 deg)
        face_normals = rotated.face_normals
        face_areas = rotated.area_faces
        overhang_mask = face_normals[:, 2] < -np.cos(np.radians(45))
        support_area = float(np.sum(face_areas[overhang_mask]))

        # Stability: higher center of gravity = less stable
        centroid_z = rotated.centroid[2] - rotated.bounds[0][2]
        max_z = extents[2]
        instability = centroid_z / max(max_z, 1e-6)

        # Normalize each term to [0, 1] range for comparable weighting
        total_area = float(np.sum(mesh.area_faces))
        max_extent = float(max(extents))
        norm_support = support_area / max(total_area, 1e-6)
        norm_height = z_height / max(max_extent, 1e-6)

        w = self.config
        score = (
            w.weight_support_area * norm_support
            + w.weight_height * norm_height
            + w.weight_stability * instability
        )
        return score

    def find_best_orientation(
        self, mesh: trimesh.Trimesh
    ) -> tuple[np.ndarray, float, list[tuple[str, float]]]:
        """Search 6 cardinal directions, return best rotation + all scores."""
        all_scores: list[tuple[str, float]] = []
        best_rotation = np.eye(4)
        best_score = float("inf")

        for name, rotation in _CARDINAL_ROTATIONS:
            score = self.evaluate_orientation(mesh, rotation)
            all_scores.append((name, score))
            if score < best_score:
                best_score = score
                best_rotation = rotation

        return best_rotation, best_score, all_scores

    async def execute(self, ctx: Any) -> None:
        """Execute basic orientation optimization."""
        import asyncio

        asset = ctx.get_asset("final_mesh")
        mesh = await asyncio.to_thread(trimesh.load, asset.path, force="mesh")

        await ctx.dispatch_progress(1, 3, "\u65b9\u5411\u8bc4\u4f30\u4e2d")

        best_rotation, best_score, all_scores = await asyncio.to_thread(
            self.find_best_orientation, mesh
        )

        await ctx.dispatch_progress(2, 3, "\u5e94\u7528\u6700\u4f18\u65b9\u5411")

        mesh.apply_transform(best_rotation)
        z_offset = -mesh.bounds[0][2]
        if abs(z_offset) > 1e-6:
            mesh.apply_translation([0, 0, z_offset])

        import tempfile
        from pathlib import Path

        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "orient"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{ctx.job_id}_oriented.glb")
        await asyncio.to_thread(mesh.export, output_path)

        best_name = next(
            name for name, score in all_scores if score == best_score
        )
        ctx.put_asset(
            "oriented_mesh", output_path, "mesh",
            metadata={
                "orientation": best_name,
                "score": round(best_score, 4),
                "all_scores": {name: round(s, 4) for name, s in all_scores},
            },
        )
        ctx.put_data("orientation_result", {
            "orientation": best_name,
            "score": round(best_score, 4),
        })

        await ctx.dispatch_progress(3, 3, f"\u65b9\u5411\u4f18\u5316\u5b8c\u6210: {best_name}")
