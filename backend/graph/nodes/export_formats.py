"""Export formats node — export mesh to GLB/STL/3MF bundle.

New-mode node (NodeContext signature) for builder_new.py only.
"""

from __future__ import annotations

import logging

from backend.graph.context import NodeContext
from backend.graph.registry import register_node

logger = logging.getLogger(__name__)


@register_node(
    name="export_formats",
    display_name="导出格式",
    requires=[["final_mesh", "scaled_mesh", "watertight_mesh"]],
    produces=["export_bundle"],
    input_types=["organic"],
)
async def export_formats_node(ctx: NodeContext) -> None:
    """Export mesh to multiple formats (GLB, STL, 3MF) for download.

    # TODO: 从 postprocess_organic_node 提取 export + validate + printability 逻辑
    # 具体步骤:
    #   1. 选择最佳可用 mesh (final > scaled > watertight)
    #   2. MeshPostProcessor.validate_mesh(mesh)
    #   3. mesh.export(glb/stl/3mf)
    #   4. PrintabilityChecker.check(stats)
    #   5. ctx.put_asset("export_bundle", job_dir, "directory")
    """
    # Find best available mesh (OR dependency: final > scaled > watertight)
    mesh_asset = None
    for key in ("final_mesh", "scaled_mesh", "watertight_mesh"):
        if ctx.has_asset(key):
            mesh_asset = ctx.get_asset(key)
            break

    if not mesh_asset:
        logger.warning("export_formats: no mesh asset available, skipping")
        return

    # Placeholder: register export bundle
    ctx.put_data("export_formats_status", "placeholder")
    ctx.put_data("export_source_mesh", mesh_asset.key)
    ctx.put_asset(
        "export_bundle",
        mesh_asset.path,
        "directory",
        metadata={"formats": ["glb", "stl", "3mf"], "exported": False},
    )
