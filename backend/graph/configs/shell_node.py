"""Configuration for shell_node."""

from __future__ import annotations

from pydantic import Field

from backend.graph.configs.base import BaseNodeConfig


class ShellNodeConfig(BaseNodeConfig):
    """shell_node configuration — SDF offset shelling."""

    strategy: str = "meshlib"
    wall_thickness: float = Field(2.0, gt=0, le=50.0)  # mm
    voxel_resolution: int = 0  # 0 = adaptive (min 256, max 512)
    shell_enabled: bool = False  # default off, user explicitly enables
