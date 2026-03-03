"""Tripo3DGenerateStrategy — SaaS-only via TripoProvider."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)


class Tripo3DGenerateStrategy(NodeStrategy):
    """Tripo3D mesh generation — SaaS API only.

    Wraps the existing TripoProvider for 3D generation.
    """

    def check_available(self) -> bool:
        """Available if tripo3d_api_key is configured."""
        api_key = getattr(self.config, "tripo3d_api_key", None)
        return bool(api_key)

    async def execute(self, ctx: Any) -> None:
        """Generate mesh via TripoProvider."""
        api_key = self.config.tripo3d_api_key
        timeout = getattr(self.config, "timeout", 120)
        output_format = getattr(self.config, "output_format", "glb")

        # Get generation input from context
        gen_input = ctx.get_data("confirmed_params") or ctx.get_data("generation_input")
        if gen_input is None:
            gen_input = {}
        prompt_en = gen_input.get("prompt_en", "")
        reference_image = gen_input.get("reference_image", None)

        await ctx.dispatch_progress(1, 3, "Tripo3D 生成中")

        provider = self._create_tripo_provider(api_key, ctx.job_id, timeout)

        # Build OrganicSpec-like object
        spec = _build_organic_spec(prompt_en)
        image_bytes = reference_image if isinstance(reference_image, bytes) else None

        # Bridge provider's sync on_progress callback to async dispatch_progress.
        # provider.generate() may poll status in a sync loop; the callback runs
        # on the provider's thread so we use run_coroutine_threadsafe.
        import asyncio as _aio

        _loop = _aio.get_running_loop()

        def _on_progress(msg: str, pct: float) -> None:
            _aio.run_coroutine_threadsafe(
                ctx.dispatch_progress(
                    max(1, int(pct * 2)), 3, f"Tripo3D: {msg}",
                ),
                _loop,
            )

        result_path: Path = await provider.generate(
            spec=spec,
            reference_image=image_bytes,
            on_progress=_on_progress,
        )

        await ctx.dispatch_progress(2, 3, "Tripo3D 生成完成")

        fmt = result_path.suffix.lstrip(".") or output_format
        ctx.put_asset("raw_mesh", str(result_path), fmt)
        await ctx.dispatch_progress(3, 3, "资产注册完成")

    @staticmethod
    def _create_tripo_provider(api_key: str, job_id: str, timeout: float):
        """Create TripoProvider instance."""
        import tempfile

        from backend.infra.mesh_providers.tripo import TripoProvider

        output_dir = Path(tempfile.gettempdir()) / "cadpilot" / "tripo3d"
        return TripoProvider(
            api_key=api_key,
            output_dir=output_dir,
            timeout_s=timeout,
        )


def _build_organic_spec(prompt_en: str):
    """Build a minimal OrganicSpec for provider.generate()."""
    from backend.models.organic import OrganicSpec

    return OrganicSpec(
        prompt_en=prompt_en,
        prompt_original=prompt_en,
        shape_category="organic",
    )
