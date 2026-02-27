"""Auto provider: Tripo3D first, fallback to Hunyuan3D."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger

from backend.infra.mesh_providers.base import MeshProvider
from backend.models.organic import OrganicSpec


class AutoProvider(MeshProvider):
    """Tries Tripo3D first, falls back to Hunyuan3D on failure."""

    def __init__(
        self,
        tripo: MeshProvider,
        hunyuan: MeshProvider,
    ) -> None:
        self._tripo = tripo
        self._hunyuan = hunyuan

    async def generate(
        self,
        spec: OrganicSpec,
        reference_image: bytes | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> Path:
        """Try Tripo3D first, fall back to Hunyuan3D."""
        errors: list[str] = []

        # Try Tripo3D
        try:
            logger.info("AutoProvider: trying Tripo3D")
            return await self._tripo.generate(spec, reference_image, on_progress)
        except Exception as e:
            logger.warning("AutoProvider: Tripo3D failed: {}", e)
            errors.append(f"Tripo3D: {e}")

        # Fallback to Hunyuan3D
        try:
            logger.info("AutoProvider: falling back to Hunyuan3D")
            if on_progress:
                on_progress("Falling back to Hunyuan3D...", 0.0)
            return await self._hunyuan.generate(spec, reference_image, on_progress)
        except Exception as e:
            logger.warning("AutoProvider: Hunyuan3D failed: {}", e)
            errors.append(f"Hunyuan3D: {e}")

        raise RuntimeError(f"All providers failed: {'; '.join(errors)}")

    async def check_health(self) -> bool:
        """Return True if at least one provider is healthy."""
        results = [
            await self._tripo.check_health(),
            await self._hunyuan.check_health(),
        ]
        return any(results)
