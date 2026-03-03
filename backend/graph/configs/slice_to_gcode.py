"""Configuration for slice_to_gcode node."""

from __future__ import annotations

from pydantic import field_validator

from backend.graph.configs.base import BaseNodeConfig


class SliceToGcodeConfig(BaseNodeConfig):
    """slice_to_gcode node configuration.

    Controls slicer strategy and hardware parameters for G-code generation.
    All hardware parameters are transparently passed to the CLI to avoid
    extrusion mismatch issues.
    """

    strategy: str = "prusaslicer"

    # CLI paths (auto-detected via shutil.which if None)
    prusaslicer_path: str | None = None
    orcaslicer_path: str | None = None

    # Slicing parameters
    layer_height: float = 0.2       # mm, range 0.05-0.6
    fill_density: int = 20          # %, range 0-100
    support_material: bool = False

    # Hardware parameters (must be passed to CLI)
    nozzle_diameter: float = 0.4    # mm
    filament_type: str = "PLA"

    # Process control
    timeout: int = 120              # seconds

    @field_validator("layer_height")
    @classmethod
    def _validate_layer_height(cls, v: float) -> float:
        if v < 0.05 or v > 0.6:
            raise ValueError(
                f"layer_height must be between 0.05 and 0.6, got {v}"
            )
        return v

    @field_validator("fill_density")
    @classmethod
    def _validate_fill_density(cls, v: int) -> int:
        if v < 0 or v > 100:
            raise ValueError(
                f"fill_density must be between 0 and 100, got {v}"
            )
        return v
