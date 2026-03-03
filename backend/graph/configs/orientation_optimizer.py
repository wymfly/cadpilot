"""Configuration for orientation_optimizer node."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from backend.graph.configs.neural import NeuralStrategyConfig


class OrientationOptimizerConfig(NeuralStrategyConfig):
    """orientation_optimizer node configuration."""

    strategy: Literal["basic", "scipy", "auto"] = "basic"

    # Scoring weights (higher = more important)
    weight_support_area: float = 0.4
    weight_height: float = 0.3
    weight_stability: float = 0.3

    # Scipy-specific
    scipy_max_iter: int = 100
    scipy_popsize: int = 15

    @field_validator("weight_support_area", "weight_height", "weight_stability")
    @classmethod
    def _positive_weight(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Weight must be non-negative, got {v}")
        return v
