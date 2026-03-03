"""slice_to_gcode — slicer node for G-code generation.

Supports PrusaSlicer and OrcaSlicer via strategy pattern.
Best mesh selection: final_mesh > scaled_mesh > watertight_mesh.
Non-STL formats are auto-converted via convert_mesh.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from backend.core.mesh_converter import convert_mesh
from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
from backend.graph.context import AssetEntry, NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.slice.orcaslicer import OrcaSlicerStrategy
from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

logger = logging.getLogger(__name__)

# Priority order for mesh selection
_MESH_PRIORITY = ["final_mesh", "scaled_mesh", "watertight_mesh"]


@register_node(
    name="slice_to_gcode",
    display_name="切片出码",
    requires=[["final_mesh", "scaled_mesh", "watertight_mesh"]],
    produces=["gcode_bundle"],
    input_types=["organic"],
    config_model=SliceToGcodeConfig,
    strategies={
        "prusaslicer": PrusaSlicerStrategy,
        "orcaslicer": OrcaSlicerStrategy,
    },
    fallback_chain=["prusaslicer", "orcaslicer"],
    default_strategy="prusaslicer",
    description="通过 PrusaSlicer/OrcaSlicer 切片生成 G-code，支持自动 fallback",
)
async def slice_to_gcode_node(ctx: NodeContext) -> None:
    """Execute G-code slicing via strategy dispatch.

    1. Select best available mesh (final > scaled > watertight)
    2. Convert to STL if needed
    3. Execute slicer strategy (with fallback in auto mode)
    """
    # Guard: no mesh available
    result = _select_best_mesh(ctx)
    if result is None:
        logger.info("slice_to_gcode: no mesh available, skipping")
        ctx.put_data("slice_status", "skipped_no_mesh")
        return

    mesh_key, asset = result
    logger.info("slice_to_gcode: using %s from %s", mesh_key, asset.path)

    # Ensure STL format
    stl_path = _ensure_stl(asset, ctx.job_id)
    ctx._slice_input_path = stl_path  # type: ignore[attr-defined]

    ctx.put_data("slice_input_mesh", mesh_key)

    # Strategy dispatch
    if ctx.config.strategy == "auto":
        await ctx.execute_with_fallback()
    else:
        strategy = ctx.get_strategy()
        await strategy.execute(ctx)


def _select_best_mesh(ctx: NodeContext) -> tuple[str, AssetEntry] | None:
    """Select best available mesh by priority order.

    Returns (key, asset) or None if no mesh is available.
    """
    for key in _MESH_PRIORITY:
        if ctx.has_asset(key):
            return key, ctx.get_asset(key)
    return None


def _ensure_stl(asset: AssetEntry, job_id: str) -> Path:
    """Ensure mesh is in STL format, converting if necessary.

    Returns path to STL file (original or converted).
    """
    asset_path = Path(asset.path)
    fmt = asset.format.lower() if asset.format else asset_path.suffix.lstrip(".").lower()

    if fmt == "stl":
        return asset_path

    # Convert to STL
    tmp_dir = Path(tempfile.gettempdir()) / "cadpilot" / job_id
    tmp_dir.mkdir(parents=True, exist_ok=True)

    converted = convert_mesh(asset_path, "stl", tmp_dir)
    logger.info("Converted %s (%s) -> STL: %s", asset_path, fmt, converted)
    return converted
