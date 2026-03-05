"""shell_node — SDF offset shelling for hollow thin-wall structures.

Passthrough when shell_enabled=False: scaled_mesh -> shelled_mesh (zero cost).
When enabled: MeshLib SDF offset creates hollow body with specified wall thickness.
"""

from __future__ import annotations

import logging

from backend.graph.configs.shell_node import ShellNodeConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.shell.meshlib_shell import MeshLibShellStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="shell_node",
    display_name="抽壳",
    requires=["scaled_mesh"],
    produces=["shelled_mesh"],
    input_types=["organic"],
    config_model=ShellNodeConfig,
    strategies={"meshlib": MeshLibShellStrategy},
    default_strategy="meshlib",
    non_fatal=False,
    description="SDF 偏移抽壳，将实心 mesh 转为指定壁厚的中空薄壁体",
)
async def shell_node_fn(ctx: NodeContext) -> None:
    """Execute mesh shelling or passthrough."""
    if not ctx.has_asset("scaled_mesh"):
        logger.warning("shell_node: no scaled_mesh asset, skipping")
        ctx.put_data("shell_node_status", "skipped_no_input")
        return

    if not ctx.config.shell_enabled:
        # Passthrough: zero-cost copy
        scaled = ctx.get_asset("scaled_mesh")
        ctx.put_asset(
            "shelled_mesh", scaled.path, "mesh",
            metadata={"passthrough": True, "shelled": False},
        )
        ctx.put_data("shell_node_status", "passthrough")
        logger.info("shell_node: shell_enabled=False, passthrough")
        return

    # Dispatch to strategy (MeshLib SDF offset)
    strategy = ctx.get_strategy()
    await strategy.execute(ctx)
    ctx.put_data("shell_node_status", "completed")
