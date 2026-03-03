"""Mesh scale node — uniform scaling with Z-align and XY-center.

New-mode node (NodeContext signature) for builder_new.py only.

Execution order:
  1. Uniform scale: scale_factor = min(target[i] / current_extent[i])
  2. Z=0 bottom alignment: translate Z so bbox.min.z = 0
  3. XY centroid centering: translate XY so centroid X=0, Y=0
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import numpy as np

from backend.graph.context import NodeContext
from backend.graph.registry import register_node

logger = logging.getLogger(__name__)


@register_node(
    name="mesh_scale",
    display_name="网格缩放",
    requires=["watertight_mesh"],
    produces=["scaled_mesh"],
    input_types=["organic"],
)
async def mesh_scale_node(ctx: NodeContext) -> None:
    """Scale mesh to match target bounding box from organic spec.

    Steps:
      1. Load watertight_mesh from asset registry
      2. Read OrganicSpec.final_bounding_box from ctx data
      3. If no target bbox -> passthrough (copy asset as-is)
      4. Uniform scale to fit target bbox (preserves aspect ratio)
      5. Align bottom face to Z=0
      6. Center XY centroid at origin
      7. Export and register as scaled_mesh asset
    """
    import trimesh

    # Guard: skip if no input mesh
    if not ctx.has_asset("watertight_mesh"):
        logger.warning("mesh_scale: no watertight_mesh asset, skipping")
        ctx.put_data("mesh_scale_status", "skipped_no_input")
        return

    watertight = ctx.get_asset("watertight_mesh")

    # Read target bounding box from OrganicSpec
    target_bbox = _get_target_bbox(ctx)

    if target_bbox is None:
        # Passthrough: no scaling needed
        logger.info("mesh_scale: no target bounding box, passing through")
        ctx.put_data("mesh_scale_status", "passthrough")
        ctx.put_asset(
            "scaled_mesh",
            watertight.path,
            "mesh",
            metadata={"scaled": False, "passthrough": True},
        )
        return

    # Load mesh and perform transformations in thread (CPU-intensive)
    mesh, scale_factor, final_extents, output_path = await asyncio.to_thread(
        _scale_mesh_sync, trimesh, watertight.path, target_bbox, ctx.job_id,
    )
    metadata = {
        "scaled": True,
        "scale_factor": round(float(scale_factor), 6),
        "target_bounding_box": {
            "x": target_bbox[0],
            "y": target_bbox[1],
            "z": target_bbox[2],
        },
        "bounding_box": {
            "x": round(float(final_extents[0]), 2),
            "y": round(float(final_extents[1]), 2),
            "z": round(float(final_extents[2]), 2),
        },
    }

    ctx.put_data("mesh_scale_status", "scaled")
    ctx.put_asset("scaled_mesh", output_path, "mesh", metadata=metadata)
    logger.info(
        "mesh_scale: done — factor=%.4f, extents=(%.1f, %.1f, %.1f)",
        scale_factor,
        *final_extents,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scale_mesh_sync(
    trimesh_mod: object,
    mesh_path: str,
    target_bbox: tuple[float, float, float],
    job_id: str,
) -> tuple[object, float, object, str]:
    """Synchronous mesh scaling — runs in thread to avoid blocking event loop."""
    mesh = _load_mesh(trimesh_mod, mesh_path)

    # Step 1: Uniform scale
    scale_factor = _compute_uniform_scale(mesh, target_bbox)
    if abs(scale_factor - 1.0) > 1e-6:
        mesh.apply_scale(scale_factor)
        logger.info(
            "mesh_scale: scaled by %.4fx to fit target (%.1f, %.1f, %.1f)",
            scale_factor,
            *target_bbox,
        )

    # Step 2: Z=0 bottom alignment
    bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
    z_offset = -bounds[0][2]
    if abs(z_offset) > 1e-6:
        mesh.apply_translation([0, 0, z_offset])
        logger.info("mesh_scale: Z-aligned bottom to Z=0 (offset=%.4f)", z_offset)

    # Step 3: XY centroid centering
    centroid = mesh.centroid
    if abs(centroid[0]) > 1e-6 or abs(centroid[1]) > 1e-6:
        mesh.apply_translation([-centroid[0], -centroid[1], 0])
        logger.info(
            "mesh_scale: XY-centered (offset=[%.4f, %.4f])",
            -centroid[0],
            -centroid[1],
        )

    output_path = _export_mesh(mesh, job_id)
    final_extents = mesh.bounding_box.extents
    return mesh, scale_factor, final_extents, output_path


def _get_target_bbox(ctx: NodeContext) -> tuple[float, float, float] | None:
    """Extract final_bounding_box from OrganicSpec in context data."""
    organic_spec = ctx.get_data("organic_spec")
    if organic_spec is None:
        return None

    # OrganicSpec can be a Pydantic model or a dict
    if hasattr(organic_spec, "final_bounding_box"):
        return organic_spec.final_bounding_box
    elif isinstance(organic_spec, dict):
        return organic_spec.get("final_bounding_box")

    return None


def _load_mesh(trimesh_mod: object, path: str) -> object:
    """Load mesh from file, handling scenes with multiple meshes."""
    loaded = trimesh_mod.load(path, force="mesh")  # type: ignore[union-attr]
    return loaded


def _compute_uniform_scale(
    mesh: object,
    target_bbox: tuple[float, float, float],
) -> float:
    """Compute uniform scale factor: min(target[i] / current[i])."""
    current_extents = mesh.bounding_box.extents  # type: ignore[union-attr]
    target = np.array(target_bbox, dtype=float)

    # Avoid division by zero for degenerate dimensions
    safe_extents = np.maximum(current_extents, 1e-6)
    scale_factors = target / safe_extents
    return float(np.min(scale_factors))


def _export_mesh(mesh: object, job_id: str) -> str:
    """Export mesh to a temporary GLB file and return the path."""
    output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "mesh_scale"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"{job_id}_scaled.glb")
    mesh.export(output_path)  # type: ignore[union-attr]
    return output_path
