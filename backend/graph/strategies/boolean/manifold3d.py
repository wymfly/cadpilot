"""Manifold3DStrategy — manifold check gate + boolean difference cuts.

Flow:
  1. Load shelled_mesh -> is_manifold_check (trimesh.is_watertight)
  2. Manifold -> execute boolean cuts directly
  3. Non-manifold -> force_voxelize(resolution) via manifold3d
  4. Recheck -> manifold -> execute boolean cuts
  5. Still non-manifold -> 2x resolution retry
  6. Still fails -> skip_on_non_manifold decides: raise or passthrough
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from backend.graph.descriptor import NodeStrategy
from backend.models.organic import (
    FlatBottomCut,
    HoleCut,
    SlotCut,
)

logger = logging.getLogger(__name__)


class Manifold3DStrategy(NodeStrategy):
    """Boolean assembly via manifold3d with voxel repair gate."""

    async def execute(self, ctx: Any) -> None:
        """Execute manifold check gate + boolean cuts."""
        config = ctx.config
        voxel_resolution = getattr(config, "voxel_resolution", 128)
        skip_on_non_manifold = getattr(config, "skip_on_non_manifold", False)

        # 1. Load mesh
        asset = ctx.get_asset("shelled_mesh")
        mesh = await asyncio.to_thread(trimesh.load, asset.path, force="mesh")

        # 2. Get cuts from organic_spec
        organic_spec = ctx.get_data("organic_spec")
        cuts = _extract_cuts(organic_spec)

        await ctx.dispatch_progress(1, len(cuts) + 2, "流形校验中")

        # 3. Manifold check gate
        if mesh.is_watertight:
            logger.info("boolean_assemble: mesh is manifold, proceeding directly")
            working_mesh = mesh
        else:
            logger.info("boolean_assemble: mesh is non-manifold, attempting voxel repair")
            working_mesh = await self._manifold_gate(
                mesh, voxel_resolution, skip_on_non_manifold, ctx, asset.path
            )
            if working_mesh is None:
                # skip_on_non_manifold=True -> passthrough handled inside _manifold_gate
                return

        await ctx.dispatch_progress(2, len(cuts) + 2, "开始布尔运算")

        # 4. Execute boolean cuts
        import manifold3d

        result_mesh, cuts_applied, cut_warnings = await asyncio.to_thread(
            self._execute_boolean_cuts, working_mesh, cuts, manifold3d
        )

        # 5. Report per-cut progress
        for i in range(len(cuts)):
            await ctx.dispatch_progress(
                i + 3, len(cuts) + 2, f"切割 {i + 1}/{len(cuts)}"
            )

        # 6. Handle results
        total_cuts = len(cuts)
        if cuts_applied == 0 and total_cuts > 0:
            # All cuts failed
            quality_mode = _get_quality_mode(organic_spec)
            if quality_mode == "draft":
                ctx.put_data("boolean_assemble_status", "passthrough_draft_all_failed")
                ctx.put_asset(
                    "final_mesh", asset.path, "mesh",
                    metadata={"cuts_applied": 0, "passthrough": True},
                )
                return
            raise RuntimeError(
                f"All {total_cuts} cuts failed. Warnings: {cut_warnings}"
            )

        if cuts_applied < total_cuts:
            ctx.put_data("boolean_assemble_status", "partial_cuts")
        else:
            ctx.put_data("boolean_assemble_status", "completed")

        # 7. Save result
        output_path = self._save_mesh(result_mesh, ctx.job_id)
        ctx.put_asset(
            "final_mesh", output_path, "mesh",
            metadata={
                "cuts_applied": cuts_applied,
                "cuts_total": total_cuts,
                "warnings": cut_warnings,
            },
        )

        await ctx.dispatch_progress(
            len(cuts) + 2, len(cuts) + 2, f"布尔运算完成: {cuts_applied}/{total_cuts}"
        )

    async def _manifold_gate(
        self,
        mesh: Any,
        resolution: int,
        skip_on_non_manifold: bool,
        ctx: Any,
        original_path: str,
    ) -> Any | None:
        """Manifold check gate with voxel repair + 2x retry.

        Returns:
            Repaired manifold mesh, or None if skip_on_non_manifold=True
            and repair failed (passthrough handled internally).
        Raises:
            RuntimeError if skip_on_non_manifold=False and repair failed.
        """
        # First attempt at original resolution
        repaired = await asyncio.to_thread(self._force_voxelize, mesh, resolution)
        if repaired.is_watertight:
            logger.info("boolean_assemble: voxel repair succeeded at resolution %d", resolution)
            return repaired

        # 2x resolution retry
        doubled = resolution * 2
        logger.info(
            "boolean_assemble: first voxelization failed, retrying at 2x resolution (%d)",
            doubled,
        )
        repaired = await asyncio.to_thread(self._force_voxelize, mesh, doubled)
        if repaired.is_watertight:
            logger.info("boolean_assemble: voxel repair succeeded at 2x resolution %d", doubled)
            return repaired

        # Both attempts failed
        if skip_on_non_manifold:
            logger.warning(
                "boolean_assemble: voxel repair failed, skip_on_non_manifold=True, "
                "passing through original mesh"
            )
            ctx.put_data("boolean_assemble_status", "passthrough_non_manifold")
            ctx.put_asset(
                "final_mesh", original_path, "mesh",
                metadata={"passthrough": True, "reason": "non_manifold_repair_failed"},
            )
            return None

        raise RuntimeError(
            "failed_non_manifold: Voxel repair failed at both "
            f"{resolution} and {doubled} resolution. "
            "Set skip_on_non_manifold=True to passthrough."
        )

    @staticmethod
    def _force_voxelize(mesh: Any, resolution: int) -> Any:
        """Voxelize mesh for manifold repair using resolution-based pitch.

        Uses trimesh voxelization at the given resolution to reconstruct a
        watertight mesh from a potentially non-manifold input. Higher
        resolution preserves more detail but is slower.
        """
        try:
            if resolution <= 0:
                logger.warning("Invalid voxel resolution %d, returning original mesh", resolution)
                return mesh

            # Compute voxel pitch from resolution and mesh extent
            max_extent = float(max(mesh.bounding_box.extents))
            if max_extent < 1e-10:
                return mesh  # degenerate mesh
            pitch = max_extent / resolution

            voxelized = mesh.voxelized(pitch=pitch).fill()
            repaired = voxelized.marching_cubes

            if len(repaired.vertices) == 0:
                return mesh  # return original on failure

            return repaired
        except (ValueError, AttributeError, RuntimeError) as exc:
            logger.warning("Voxelization failed at resolution %d: %s", resolution, exc)
            return mesh  # return original on failure

    @staticmethod
    def _execute_boolean_cuts(
        mesh: Any,
        cuts: list,
        manifold3d: Any,
    ) -> tuple[Any, int, list[str]]:
        """Execute boolean difference cuts using manifold3d.

        Returns: (result_mesh, cuts_applied, warnings)
        """
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
                msg = f"切割 #{i + 1} ({type(cut).__name__}) 失败: {e}"
                logger.warning("Failed to apply cut %d: %s", i + 1, e)
                warnings.append(msg)

        # Early return: no cuts succeeded -> return original mesh + count
        if cuts_applied == 0:
            return mesh, 0, warnings

        result_mesh_data = manifold_mesh.to_mesh()
        verts = np.asarray(result_mesh_data.vert_properties)
        faces = np.asarray(result_mesh_data.tri_verts)

        if len(verts) == 0 or verts.ndim < 2:
            raise ValueError("Boolean operation produced empty mesh")

        result = trimesh.Trimesh(vertices=verts[:, :3], faces=faces)
        return result, cuts_applied, warnings

    @staticmethod
    def _save_mesh(mesh: Any, job_id: str) -> str:
        """Export result mesh to temp file and return path."""
        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "boolean_assemble"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"{job_id}_final.glb")
        mesh.export(output_path)
        return output_path


# ---------------------------------------------------------------------------
# Internal helpers (extracted from mesh_post_processor.py)
# ---------------------------------------------------------------------------


def _extract_cuts(organic_spec: Any) -> list:
    """Extract engineering_cuts from organic_spec (Pydantic or dict)."""
    if organic_spec is None:
        return []
    if hasattr(organic_spec, "engineering_cuts"):
        return organic_spec.engineering_cuts or []
    if isinstance(organic_spec, dict):
        return organic_spec.get("engineering_cuts", [])
    return []


def _get_quality_mode(organic_spec: Any) -> str:
    """Extract quality_mode from organic_spec."""
    if organic_spec is None:
        return "standard"
    if hasattr(organic_spec, "quality_mode"):
        return organic_spec.quality_mode
    if isinstance(organic_spec, dict):
        return organic_spec.get("quality_mode", "standard")
    return "standard"


def _create_cut_tool(
    cut: object,
    mesh_extents: np.ndarray,
    manifold3d: object,
) -> object | None:
    """Create a manifold3d tool shape for a given cut type.

    Extracted from MeshPostProcessor.apply_boolean_cuts() for reuse
    in the strategy-based pipeline.
    """
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
