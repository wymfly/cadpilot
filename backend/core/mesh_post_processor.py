"""Mesh post-processing pipeline: repair → scale → boolean cuts → validate.

Heavy dependencies (manifold3d, pymeshlab) are lazy-loaded inside functions
to avoid import errors when they're not installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import trimesh
from loguru import logger

from backend.models.organic import (
    FlatBottomCut,
    HoleCut,
    MeshStats,
    OrganicSpec,
    SlotCut,
)


@dataclass
class RepairInfo:
    """Result of mesh repair step."""
    status: Literal["success", "degraded"]
    message: str


@dataclass
class ProcessedMeshResult:
    """Result of mesh post-processing."""
    mesh: trimesh.Trimesh
    stats: MeshStats
    warnings: list[str] = field(default_factory=list)


class MeshPostProcessor:
    """Pipeline: repair → scale → boolean cuts → quality validation."""

    async def process(
        self,
        raw_mesh_path: Path,
        spec: OrganicSpec,
        on_progress: Callable[[str, str], None] | None = None,
    ) -> ProcessedMeshResult:
        """Process a raw mesh through the full pipeline.

        Backward-compatible orchestrator. For fine-grained control,
        call individual step methods directly.
        """
        warnings: list[str] = []

        mesh = self.load_mesh(raw_mesh_path)
        if on_progress:
            on_progress("load", "Mesh loaded")

        mesh, repair_info = self.repair_mesh(mesh)
        if on_progress:
            on_progress("repair", repair_info.message)
        if repair_info.status == "degraded":
            warnings.append(repair_info.message)

        if spec.final_bounding_box:
            mesh = self.scale_mesh(mesh, spec.final_bounding_box)
            if on_progress:
                on_progress("scale", "Mesh scaled to target bounding box")

        boolean_cuts_applied = 0
        if spec.quality_mode != "draft" and spec.engineering_cuts:
            try:
                mesh, boolean_cuts_applied, cut_warnings = self.apply_boolean_cuts(
                    mesh, spec.engineering_cuts
                )
                warnings.extend(cut_warnings)
                if on_progress:
                    on_progress("boolean", f"Applied {boolean_cuts_applied} boolean cuts")
            except Exception as e:
                msg = f"Boolean cuts failed, returning mesh without cuts: {e}"
                logger.warning(msg)
                warnings.append(msg)
                if on_progress:
                    on_progress("boolean", msg)

        stats = self.validate_mesh(mesh, boolean_cuts_applied)
        if on_progress:
            on_progress("validate", "Quality validation complete")

        return ProcessedMeshResult(mesh=mesh, stats=stats, warnings=warnings)

    # ------------------------------------------------------------------
    # Public step methods
    # ------------------------------------------------------------------

    @staticmethod
    def load_mesh(path: Path) -> trimesh.Trimesh:
        """Load mesh from file, handling scenes with multiple meshes."""
        loaded = trimesh.load(str(path))
        if isinstance(loaded, trimesh.Scene):
            meshes = list(loaded.geometry.values())
            if not meshes:
                raise ValueError(f"No meshes found in {path}")
            mesh = trimesh.util.concatenate(meshes)
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            raise ValueError(f"Unexpected type from trimesh.load: {type(loaded)}")
        return mesh

    @staticmethod
    def repair_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, RepairInfo]:
        """Repair mesh topology. Returns (repaired_mesh, repair_info).

        Tries PyMeshLab first (thorough), falls back to trimesh (basic).
        """
        try:
            import pymeshlab  # type: ignore[import-untyped]

            if not hasattr(pymeshlab, "__file__"):
                raise ImportError("pymeshlab appears to be a stub")

            ms = pymeshlab.MeshSet()
            m = pymeshlab.Mesh(mesh.vertices, mesh.faces)
            ms.add_mesh(m)
            ms.meshing_repair_non_manifold_edges()
            ms.meshing_repair_non_manifold_vertices()
            ms.meshing_close_holes()
            ms.meshing_re_orient_faces_coherentely()
            result = ms.current_mesh()
            verts = np.asarray(result.vertex_matrix())
            faces_arr = np.asarray(result.face_matrix())
            if len(verts) == 0:
                raise ValueError("PyMeshLab returned empty mesh")
            mesh = trimesh.Trimesh(vertices=verts, faces=faces_arr)
            logger.info("Mesh repaired with PyMeshLab")
            return mesh, RepairInfo(status="success", message="PyMeshLab 修复完成")
        except Exception as e:
            logger.info("PyMeshLab not available, using trimesh repair: {}", e)
            trimesh.repair.fix_normals(mesh)
            trimesh.repair.fix_winding(mesh)
            trimesh.repair.fill_holes(mesh)
            return mesh, RepairInfo(
                status="degraded",
                message="降级为 trimesh 基础修复（PyMeshLab 不可用）",
            )

    @staticmethod
    def scale_mesh(
        mesh: trimesh.Trimesh,
        target_bbox: tuple[float, float, float],
    ) -> trimesh.Trimesh:
        """Scale mesh to fit within target bounding box (uniform scale)."""
        current_extents = mesh.bounding_box.extents
        target = np.array(target_bbox, dtype=float)

        scale_factors = target / np.maximum(current_extents, 1e-6)
        uniform_scale = float(np.min(scale_factors))

        if abs(uniform_scale - 1.0) > 1e-6:
            mesh.apply_scale(uniform_scale)
            logger.info(
                "Scaled mesh by {:.3f}x to fit ({:.1f}, {:.1f}, {:.1f})",
                uniform_scale,
                *target_bbox,
            )

        mesh.apply_translation(-mesh.centroid)
        return mesh

    @staticmethod
    def apply_boolean_cuts(
        mesh: trimesh.Trimesh,
        cuts: list[object],
    ) -> tuple[trimesh.Trimesh, int, list[str]]:
        """Apply engineering cuts. Returns (mesh, cuts_applied, warnings)."""
        import manifold3d

        if not hasattr(manifold3d, "__file__"):
            raise ImportError("manifold3d appears to be a stub")

        manifold_mesh = manifold3d.Manifold.from_mesh(
            manifold3d.Mesh(
                vert_properties=np.array(mesh.vertices, dtype=np.float32),
                tri_verts=np.array(mesh.faces, dtype=np.uint32),
            )
        )

        cuts_applied = 0
        warnings: list[str] = []
        for i, cut in enumerate(cuts):
            try:
                tool = _create_cut_tool(cut, mesh.bounding_box.extents, manifold3d)
                if tool is not None:
                    manifold_mesh = manifold_mesh - tool
                    cuts_applied += 1
            except Exception as e:
                msg = f"切割 #{i + 1} 失败: {e}"
                logger.warning("Failed to apply cut {}: {}", cut, e)
                warnings.append(msg)

        result_mesh_data = manifold_mesh.to_mesh()
        verts = np.asarray(result_mesh_data.vert_properties)
        faces_arr = np.asarray(result_mesh_data.tri_verts)
        if len(verts) == 0 or verts.ndim < 2:
            raise ValueError("Boolean operation produced empty mesh")
        result = trimesh.Trimesh(
            vertices=verts[:, :3],
            faces=faces_arr,
        )
        return result, cuts_applied, warnings

    @staticmethod
    def validate_mesh(
        mesh: trimesh.Trimesh,
        boolean_cuts_applied: int,
    ) -> MeshStats:
        """Compute mesh quality statistics."""
        bbox = mesh.bounding_box.extents
        volume = float(mesh.volume) if mesh.is_watertight else None
        volume_cm3 = volume / 1000.0 if volume is not None else None

        return MeshStats(
            vertex_count=len(mesh.vertices),
            face_count=len(mesh.faces),
            is_watertight=mesh.is_watertight,
            volume_cm3=volume_cm3,
            bounding_box={"x": float(bbox[0]), "y": float(bbox[1]), "z": float(bbox[2])},
            has_non_manifold=not mesh.is_watertight,
            boolean_cuts_applied=boolean_cuts_applied,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _create_cut_tool(
    cut: object,
    mesh_extents: np.ndarray,
    manifold3d: object,
) -> object | None:
    """Create a manifold3d tool shape for a given cut type."""
    if isinstance(cut, FlatBottomCut):
        box_size = float(max(mesh_extents[:2])) * 2
        box_height = float(mesh_extents[2])
        tool = manifold3d.Manifold.cube(  # type: ignore[union-attr]
            [box_size, box_size, box_height]
        )
        tool = tool.translate([
            -box_size / 2,
            -box_size / 2,
            -(box_height + mesh_extents[2] / 2 - cut.offset),
        ])
        return tool

    elif isinstance(cut, HoleCut):
        radius = cut.diameter / 2
        cylinder = manifold3d.Manifold.cylinder(  # type: ignore[union-attr]
            cut.depth, radius, radius, circular_segments=64
        )
        pos = cut.position
        cylinder = cylinder.translate([pos[0], pos[1], pos[2] - cut.depth / 2])
        return cylinder

    elif isinstance(cut, SlotCut):
        slot = manifold3d.Manifold.cube(  # type: ignore[union-attr]
            [cut.width, cut.length, cut.depth]
        )
        pos = cut.position
        slot = slot.translate([
            pos[0] - cut.width / 2,
            pos[1] - cut.length / 2,
            pos[2] - cut.depth / 2,
        ])
        return slot

    return None
