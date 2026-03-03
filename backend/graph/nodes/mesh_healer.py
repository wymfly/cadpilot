"""mesh_healer — dual-channel mesh repair node.

Replaces the mesh_repair stub. Uses AlgorithmHealStrategy (diagnosis-driven
multi-tool escalation) and NeuralHealStrategy (HTTP /v1/repair via NKSR).
"""

from __future__ import annotations

import logging

from backend.graph.configs.mesh_healer import MeshHealerConfig
from backend.graph.context import NodeContext
from backend.graph.registry import register_node
from backend.graph.strategies.heal.algorithm import AlgorithmHealStrategy
from backend.graph.strategies.heal.neural import NeuralHealStrategy

logger = logging.getLogger(__name__)


@register_node(
    name="mesh_healer",
    display_name="网格修复",
    requires=["raw_mesh"],
    produces=["watertight_mesh"],
    input_types=["organic"],
    config_model=MeshHealerConfig,
    strategies={
        "algorithm": AlgorithmHealStrategy,
        "neural": NeuralHealStrategy,
    },
    default_strategy="algorithm",
    fallback_chain=["algorithm", "neural"],
    description="诊断网格缺陷并修复为水密网格，支持 algorithm/neural/auto 三种策略",
)
async def mesh_healer_node(ctx: NodeContext) -> None:
    """Execute mesh healing via strategy dispatch.

    For auto mode, uses ctx.execute_with_fallback() which tries
    algorithm first, falls back to neural if algorithm fails.
    """
    # Guard: skip if upstream failed (no mesh to heal)
    try:
        ctx.get_asset("raw_mesh")
    except KeyError:
        if not ctx.get_data("raw_mesh_path"):
            logger.info("mesh_healer: no raw mesh available, skipping")
            ctx.put_data("mesh_healer_status", "skipped_no_input")
            return

    if ctx.config.strategy == "auto":
        await ctx.execute_with_fallback()
    else:
        strategy = ctx.get_strategy()
        await strategy.execute(ctx)

    # Optional retopo sub-step
    config = ctx.config
    if config.retopo_enabled:
        await _maybe_retopo(ctx, config)


async def _maybe_retopo(ctx: NodeContext, config: MeshHealerConfig) -> None:
    """Run retopo if face count exceeds threshold and retopo is configured."""
    import trimesh

    asset = ctx.get_asset("watertight_mesh")
    mesh = trimesh.load(asset.path, force="mesh")

    if len(mesh.faces) <= config.retopo_threshold:
        return

    if not config.retopo_endpoint:
        logger.warning(
            "Retopo triggered (faces=%d > threshold=%d) but no endpoint configured",
            len(mesh.faces),
            config.retopo_threshold,
        )
        return

    await ctx.dispatch_progress(
        0, 1, f"Retopo: {len(mesh.faces)} → {config.retopo_target_faces} faces"
    )

    logger.info(
        "Running retopo: %d faces > threshold %d",
        len(mesh.faces),
        config.retopo_threshold,
    )
    import httpx

    async with httpx.AsyncClient(timeout=config.neural_timeout) as client:
        resp = await client.post(
            f"{config.retopo_endpoint.rstrip('/')}/v1/retopo",
            json={
                "mesh_uri": asset.path,
                "target_faces": config.retopo_target_faces,
            },
        )
        resp.raise_for_status()
        result = resp.json()

    ctx.put_asset(
        "watertight_mesh",
        result["mesh_uri"],
        "obj",
        metadata=result.get("metrics", {}),
    )

    await ctx.dispatch_progress(1, 1, "Retopo 完成")
