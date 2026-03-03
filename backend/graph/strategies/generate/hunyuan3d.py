"""Hunyuan3DGenerateStrategy — dual deployment (local + SaaS).

Priority:
1. Local endpoint (POST /v1/generate) — if configured and healthy
2. SaaS via HunyuanProvider — if api_key configured
3. Both configured: local first, SaaS fallback on local failure
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.graph.strategies.generate.base import LocalModelStrategy

logger = logging.getLogger(__name__)


class Hunyuan3DGenerateStrategy(LocalModelStrategy):
    """Hunyuan3D mesh generation with local + SaaS dual deployment."""

    def check_available(self) -> bool:
        """Three-state availability check.

        - Local endpoint healthy -> True
        - Local unhealthy but SaaS api_key -> True (SaaS fallback)
        - Local-only unhealthy -> False
        - SaaS-only (no endpoint) with api_key -> True
        - Neither configured -> False
        """
        endpoint = getattr(self.config, "hunyuan3d_endpoint", None)
        api_key = getattr(self.config, "hunyuan3d_api_key", None)

        if endpoint:
            if self._check_endpoint_health(endpoint):
                return True
            # Local unhealthy — check SaaS fallback
            return bool(api_key)

        # No local endpoint — SaaS only
        return bool(api_key)

    async def execute(self, ctx: Any) -> None:
        """Execute generation: local priority, SaaS fallback."""
        endpoint = getattr(self.config, "hunyuan3d_endpoint", None)
        api_key = getattr(self.config, "hunyuan3d_api_key", None)
        timeout = getattr(self.config, "timeout", 120)
        output_format = getattr(self.config, "output_format", "glb")

        # Get generation input from context
        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input")
        if gen_input is None:
            gen_input = {}
        prompt_en = gen_input.get("prompt_en", "")
        reference_image = gen_input.get("reference_image", None)

        await ctx.dispatch_progress(1, 3, "Hunyuan3D 生成中")

        # Try local endpoint first
        if endpoint and self._check_endpoint_health(endpoint):
            try:
                data, content_type = await self._post_generate(
                    endpoint=endpoint,
                    image_data=reference_image if isinstance(reference_image, bytes) else None,
                    params={"prompt": prompt_en, "format": output_format},
                    timeout=timeout,
                )
                suffix = _infer_suffix(content_type, output_format)
                output_path = self._save_output(data, ctx.job_id, suffix, "hunyuan3d")

                await ctx.dispatch_progress(2, 3, "本地生成完成")
                ctx.put_asset("raw_mesh", output_path, output_format)
                await ctx.dispatch_progress(3, 3, "资产注册完成")
                return
            except Exception as exc:
                if not api_key:
                    raise
                logger.warning(
                    "Hunyuan3D local endpoint failed, falling back to SaaS: %s",
                    exc,
                )

        # SaaS fallback (or SaaS-only)
        if not api_key:
            raise RuntimeError(
                "Hunyuan3D: no local endpoint available and no SaaS API key"
            )

        await ctx.dispatch_progress(1, 3, "Hunyuan3D SaaS 生成中")
        provider = self._create_hunyuan_provider(api_key, ctx.job_id, timeout)

        # Build OrganicSpec-like object for provider
        spec = _build_organic_spec(prompt_en)
        image_bytes = reference_image if isinstance(reference_image, bytes) else None

        # Bridge provider's sync on_progress to async dispatch_progress
        import asyncio as _aio

        _loop = _aio.get_running_loop()

        def _on_progress(msg: str, pct: float) -> None:
            _aio.run_coroutine_threadsafe(
                ctx.dispatch_progress(
                    max(1, int(pct * 2)), 3, f"Hunyuan3D: {msg}",
                ),
                _loop,
            )

        result_path: Path = await provider.generate(
            spec=spec,
            reference_image=image_bytes,
            on_progress=_on_progress,
        )

        await ctx.dispatch_progress(2, 3, "SaaS 生成完成")
        fmt = result_path.suffix.lstrip(".") or output_format
        ctx.put_asset("raw_mesh", str(result_path), fmt)
        await ctx.dispatch_progress(3, 3, "资产注册完成")

    @staticmethod
    def _create_hunyuan_provider(api_key: str, job_id: str, timeout: float):
        """Create HunyuanProvider instance for SaaS calls."""
        import tempfile

        from backend.infra.mesh_providers.hunyuan import HunyuanProvider

        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "hunyuan3d"
        return HunyuanProvider(
            api_key=api_key,
            output_dir=output_dir,
            timeout_s=timeout,
        )


def _infer_suffix(content_type: str, fallback_format: str) -> str:
    """Infer file suffix from content-type header or fallback format."""
    ct_map = {
        "model/gltf-binary": ".glb",
        "model/gltf+json": ".gltf",
        "application/octet-stream": f".{fallback_format}",
        "model/obj": ".obj",
        "model/stl": ".stl",
    }
    return ct_map.get(content_type, f".{fallback_format}")


def _build_organic_spec(prompt_en: str):
    """Build a minimal OrganicSpec for provider.generate()."""
    from backend.models.organic import OrganicSpec

    return OrganicSpec(
        prompt_en=prompt_en,
        prompt_original=prompt_en,
        shape_category="organic",
    )
