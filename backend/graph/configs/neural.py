"""Neural strategy configuration model."""

from pydantic import Field

from backend.graph.configs.base import BaseNodeConfig


class NeuralStrategyConfig(BaseNodeConfig):
    """Configuration for nodes that support Neural channel strategies.

    Extends BaseNodeConfig with neural-specific fields.
    """

    neural_enabled: bool = Field(default=False, json_schema_extra={"x-scope": "system"})
    neural_endpoint: str | None = Field(default=None, json_schema_extra={"x-scope": "system"})
    neural_timeout: int = 60
    health_check_path: str = Field(default="/health", json_schema_extra={"x-scope": "system"})
