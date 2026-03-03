"""Configuration for mesh_healer node."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from backend.graph.configs.neural import NeuralStrategyConfig


class MeshHealerConfig(NeuralStrategyConfig):
    """mesh_healer node configuration.

    Inherits neural_enabled, neural_endpoint, neural_timeout, health_check_path
    from NeuralStrategyConfig.
    """

    strategy: Literal["algorithm", "neural", "auto"] = "algorithm"
    voxel_resolution: int = 128
    retopo_threshold: int = 100000
    retopo_enabled: bool = False
    retopo_endpoint: str | None = None
    retopo_target_faces: int = 50000

    @model_validator(mode="after")
    def _validate_neural_config(self) -> "MeshHealerConfig":
        """Ensure neural config is consistent with strategy choice."""
        if self.strategy == "neural" and not self.neural_enabled:
            raise ValueError(
                "strategy='neural' requires neural_enabled=True"
            )
        if self.strategy in ("neural", "auto") and self.neural_enabled:
            if not self.neural_endpoint:
                raise ValueError(
                    "neural_endpoint must be set when strategy is "
                    f"'{self.strategy}' and neural_enabled=True"
                )
        return self
