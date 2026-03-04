"""Configuration for generate_raw_mesh node."""

from __future__ import annotations

from pydantic import Field

from backend.graph.configs.base import BaseNodeConfig


class GenerateRawMeshConfig(BaseNodeConfig):
    """generate_raw_mesh node configuration.

    Supports 4 model strategies with dual deployment:
    - hunyuan3d: SaaS + local
    - tripo3d: SaaS only
    - spar3d: local only
    - trellis: local only
    """

    strategy: str = "hunyuan3d"

    # Hunyuan3D (SaaS + local)
    hunyuan3d_api_key: str | None = Field(
        default=None, json_schema_extra={"x-sensitive": True},
    )
    hunyuan3d_endpoint: str | None = None

    # Tripo3D (SaaS only)
    tripo3d_api_key: str | None = Field(
        default=None, json_schema_extra={"x-sensitive": True},
    )

    # SPAR3D (local only)
    spar3d_endpoint: str | None = None

    # TRELLIS (local only)
    trellis_endpoint: str | None = None

    # Common
    timeout: int = 120
    output_format: str = "glb"
