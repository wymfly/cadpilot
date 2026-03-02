"""Mesh repair node — load raw mesh and repair to watertight.

New-mode node (NodeContext signature) for builder_new.py only.
"""

from __future__ import annotations

import logging

from backend.graph.context import NodeContext
from backend.graph.registry import register_node

logger = logging.getLogger(__name__)


@register_node(
    name="mesh_repair",
    display_name="网格修复",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    input_types=["organic"],
)
async def mesh_repair_node(ctx: NodeContext) -> None:
    """Load raw mesh file and run repair to produce watertight mesh.

    # TODO: 从 postprocess_organic_node 提取 load + repair 逻辑
    # 具体步骤:
    #   1. MeshPostProcessor.load_mesh(raw_mesh_path)
    #   2. MeshPostProcessor.repair_mesh(mesh) → (mesh, repair_info)
    #   3. ctx.put_asset("watertight_mesh", repaired_path, "glb")
    """
    raw_mesh_path = ctx.get_data("raw_mesh_path")
    if not raw_mesh_path:
        logger.warning("mesh_repair: no raw_mesh_path in context, skipping")
        return

    # Placeholder: register asset so downstream nodes can resolve dependency
    ctx.put_data("mesh_repair_status", "placeholder")
    ctx.put_asset("watertight_mesh", str(raw_mesh_path), "mesh", metadata={"repaired": False})
