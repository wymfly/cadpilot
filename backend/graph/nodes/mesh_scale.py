"""Mesh scale node — scale watertight mesh to target bounding box.

New-mode node (NodeContext signature) for builder_new.py only.
"""

from __future__ import annotations

import logging

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

    # TODO: 从 postprocess_organic_node 提取 scale 逻辑
    # 具体步骤:
    #   1. 从 ctx.get_data("organic_spec") 读取 final_bounding_box
    #   2. MeshPostProcessor.scale_mesh(mesh, target_bbox)
    #   3. ctx.put_asset("scaled_mesh", scaled_path, "mesh")
    """
    if not ctx.has_asset("watertight_mesh"):
        logger.warning("mesh_scale: no watertight_mesh asset, skipping")
        return

    watertight = ctx.get_asset("watertight_mesh")

    # Placeholder: pass through watertight mesh as scaled
    ctx.put_data("mesh_scale_status", "placeholder")
    ctx.put_asset("scaled_mesh", watertight.path, "mesh", metadata={"scaled": False})
