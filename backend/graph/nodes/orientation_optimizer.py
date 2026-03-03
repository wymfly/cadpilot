"""orientation_optimizer — find optimal print orientation.

Searches rotation space to minimize: support area + print height + instability.
Strategies: basic (6-direction discrete), scipy (continuous DE), neural (future).
"""

from __future__ import annotations

import logging

from backend.graph.configs.orientation_optimizer import \
    OrientationOptimizerConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.orient.basic import BasicOrientStrategy
from backend.graph.strategies.orient.scipy_orient import ScipyOrientStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="orientation_optimizer",
    display_name="打印方向优化",
    requires=["final_mesh"],
    produces=["oriented_mesh"],
    input_types=["organic"],
    config_model=OrientationOptimizerConfig,
    strategies={
        "basic": BasicOrientStrategy,
        "scipy": ScipyOrientStrategy,
    },
    default_strategy="basic",
    fallback_chain=["scipy", "basic"],
    non_fatal=True,
    description="搜索最优打印方向，最小化支撑面积和打印高度",
)
async def orientation_optimizer_node(ctx: NodeContext) -> None:
    """Execute orientation optimization via strategy dispatch.

    non_fatal=True: orientation failure should not block the pipeline.
    If no final_mesh, skip gracefully.
    """
    if not ctx.has_asset("final_mesh"):
        logger.info("orientation_optimizer: no final_mesh, skipping")
        ctx.put_data("orientation_optimizer_status", "skipped_no_input")
        return

    if ctx.config.strategy == "auto":
        await ctx.execute_with_fallback()
    else:
        strategy = ctx.get_strategy()
        await strategy.execute(ctx)
