"""Abstract base class for mesh generation providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from backend.models.organic import OrganicSpec


class MeshProvider(ABC):
    """Base class for 3D mesh generation providers."""

    @abstractmethod
    async def generate(
        self,
        spec: OrganicSpec,
        reference_image: bytes | None = None,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> Path:
        """Generate a 3D mesh from an OrganicSpec.

        Returns the path to the downloaded mesh file (GLB/OBJ).
        """

    @abstractmethod
    async def check_health(self) -> bool:
        """Check if the provider API is reachable and the key is valid."""
