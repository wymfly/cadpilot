"""TRELLIS2GenerateStrategy — local-only via LocalModelStrategy."""

from __future__ import annotations

import logging
from typing import Any

from backend.graph.strategies.generate.base import LocalModelStrategy

logger = logging.getLogger(__name__)


class TRELLIS2GenerateStrategy(LocalModelStrategy):
    """TRELLIS.2 mesh generation — local HTTP endpoint only."""

    def check_available(self) -> bool:
        endpoint = getattr(self.config, "trellis2_endpoint", None)
        if not endpoint:
            return False
        return self._check_endpoint_health(endpoint)

    async def execute(self, ctx: Any) -> None:
        endpoint = self.config.trellis2_endpoint
        timeout = getattr(self.config, "timeout", 330)
        output_format = getattr(self.config, "output_format", "glb")

        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input") or {}
        image_b64 = self._get_image_b64(ctx)
        seed = gen_input.get("seed")

        await ctx.dispatch_progress(1, 3, "TRELLIS.2 生成中")

        data, content_type, mesh_meta = await self._post_generate(
            endpoint=endpoint,
            image_b64=image_b64,
            seed=seed,
            params={"simplify": 100000, "texture": False},
            timeout=timeout,
        )

        await ctx.dispatch_progress(2, 3, "TRELLIS.2 生成完成")

        suffix = f".{output_format}"
        output_path = self._save_output(data, ctx.job_id, suffix, "trellis2")
        ctx.put_asset("raw_mesh", output_path, output_format, metadata=mesh_meta)
        await ctx.dispatch_progress(3, 3, "资产注册完成")
