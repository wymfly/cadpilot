"""NeuralHealStrategy — HTTP-based mesh repair via NKSR model service."""

from __future__ import annotations

import logging
from typing import Any

from backend.graph.strategies.neural import NeuralStrategy

logger = logging.getLogger(__name__)


class NeuralHealStrategy(NeuralStrategy):
    """Repair mesh via Neural Kernel Surface Reconstruction (NKSR).

    Calls POST /v1/repair on the configured neural endpoint.
    """

    async def _post(self, path: str, payload: dict) -> dict:
        """POST to model service endpoint."""
        import httpx

        endpoint = self.config.neural_endpoint.rstrip("/")
        url = f"{endpoint}{path}"
        timeout = getattr(self.config, "neural_timeout", 60)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def execute(self, ctx: Any) -> None:
        # Bridge upstream contract: asset first, fallback to data
        # Note: AssetRegistry.get() raises KeyError when key not found.
        try:
            raw_asset = ctx.get_asset("raw_mesh")
            mesh_path = raw_asset.path
        except KeyError:
            mesh_path = ctx.get_data("raw_mesh_path")
            if mesh_path is None:
                raise ValueError("No raw mesh found in assets or data")

        await ctx.dispatch_progress(1, 3, "Neural 修复请求中")

        response = await self._post("/v1/repair", {
            "mesh_uri": mesh_path,
        })

        await ctx.dispatch_progress(2, 3, "Neural 修复完成")

        repaired_path = response["mesh_uri"]
        metrics = response.get("metrics", {})

        ctx.put_asset(
            "watertight_mesh",
            repaired_path,
            "obj",
            metadata=metrics,
        )

        await ctx.dispatch_progress(3, 3, "资产注册完成")
