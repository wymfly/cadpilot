"""boolean_assemble — manifold3d voxel repair gate + boolean difference cuts.

Replaces the boolean_cuts stub. Strategy-based node that:
  1. Checks if shelled_mesh is manifold (watertight)
  2. Non-manifold -> voxelization repair via manifold3d (with 2x retry)
  3. Executes boolean difference cuts (FlatBottomCut, HoleCut, SlotCut)
  4. Produces final_mesh asset

Passthrough conditions:
  - No engineering_cuts -> passthrough shelled_mesh as final_mesh
  - quality_mode="draft" -> passthrough
  - No shelled_mesh -> skipped_no_input
"""

from __future__ import annotations

import logging

from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="boolean_assemble",
    display_name="布尔装配",
    requires=["shelled_mesh"],
    produces=["final_mesh"],
    input_types=["organic"],
    config_model=BooleanAssembleConfig,
    strategies={
        "manifold3d": Manifold3DStrategy,
    },
    default_strategy="manifold3d",
    description="流形校验门 + manifold3d 布尔差集运算",
)
async def boolean_assemble_node(ctx: NodeContext) -> None:
    """Execute boolean assembly: manifold gate + boolean difference cuts.

    Passthrough conditions checked before strategy dispatch:
    - No shelled_mesh -> skipped_no_input
    - No engineering_cuts -> passthrough_no_cuts
    - quality_mode="draft" -> passthrough_draft
    """
    # Guard: no input mesh
    if not ctx.has_asset("shelled_mesh"):
        logger.warning("boolean_assemble: no shelled_mesh asset, skipping")
        ctx.put_data("boolean_assemble_status", "skipped_no_input")
        return

    # Read organic_spec for passthrough checks
    organic_spec = ctx.get_data("organic_spec")

    # Passthrough: no cuts
    cuts = _extract_cuts(organic_spec)
    if not cuts:
        logger.info("boolean_assemble: no engineering_cuts, passthrough")
        _passthrough(ctx, "passthrough_no_cuts")
        return

    # Passthrough: draft mode
    quality_mode = _get_quality_mode(organic_spec)
    if quality_mode == "draft":
        logger.info("boolean_assemble: draft mode, passthrough")
        _passthrough(ctx, "passthrough_draft")
        return

    # Dispatch to strategy
    strategy = ctx.get_strategy()
    await strategy.execute(ctx)


def _passthrough(ctx: NodeContext, status: str) -> None:
    """Pass shelled_mesh through as final_mesh."""
    scaled = ctx.get_asset("shelled_mesh")
    ctx.put_data("boolean_assemble_status", status)
    ctx.put_asset(
        "final_mesh", scaled.path, "mesh",
        metadata={"passthrough": True, "cuts_applied": 0},
    )


def _extract_cuts(organic_spec: object) -> list:
    """Extract engineering_cuts from organic_spec."""
    if organic_spec is None:
        return []
    if hasattr(organic_spec, "engineering_cuts"):
        return organic_spec.engineering_cuts or []
    if isinstance(organic_spec, dict):
        return organic_spec.get("engineering_cuts", [])
    return []


def _get_quality_mode(organic_spec: object) -> str:
    """Extract quality_mode from organic_spec."""
    if organic_spec is None:
        return "standard"
    if hasattr(organic_spec, "quality_mode"):
        return organic_spec.quality_mode
    if isinstance(organic_spec, dict):
        return organic_spec.get("quality_mode", "standard")
    return "standard"
