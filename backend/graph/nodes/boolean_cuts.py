"""Boolean cuts node — apply engineering boolean operations to mesh.

New-mode node (NodeContext signature) for builder_new.py only.
"""

from __future__ import annotations

import logging

from backend.graph.context import NodeContext
from backend.graph.registry import register_node

logger = logging.getLogger(__name__)


@register_node(
    name="boolean_cuts",
    display_name="布尔运算",
    requires=["scaled_mesh"],
    produces=["final_mesh"],
    input_types=["organic"],
)
async def boolean_cuts_node(ctx: NodeContext) -> None:
    """Apply engineering boolean cuts (holes, slots, etc.) to the scaled mesh.

    # TODO: 从 postprocess_organic_node 提取 boolean cuts 逻辑
    # 具体步骤:
    #   1. 从 ctx.get_data("organic_spec") 读取 engineering_cuts
    #   2. MeshPostProcessor.apply_boolean_cuts(mesh, cuts)
    #   3. ctx.put_asset("final_mesh", final_path, "mesh")
    """
    if not ctx.has_asset("scaled_mesh"):
        logger.warning("boolean_cuts: no scaled_mesh asset, skipping")
        return

    scaled = ctx.get_asset("scaled_mesh")

    # Placeholder: pass through scaled mesh as final
    ctx.put_data("boolean_cuts_status", "placeholder")
    ctx.put_asset("final_mesh", scaled.path, "mesh", metadata={"cuts_applied": 0})
