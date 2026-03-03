"""Configuration for thermal_simulation node."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from backend.graph.configs.neural import NeuralStrategyConfig


class ThermalSimulationConfig(NeuralStrategyConfig):
    """thermal_simulation node configuration.

    Degraded design: rules-based thermal risk report instead of FEA.
    """

    strategy: Literal["rules", "gradient", "auto"] = "rules"

    overhang_threshold: float = 45.0
    aspect_ratio_threshold: float = 10.0
    large_flat_area_threshold: float = 100.0

    @field_validator("overhang_threshold")
    @classmethod
    def _positive_threshold(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Threshold must be positive, got {v}")
        return v
