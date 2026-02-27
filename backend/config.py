"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """CAD3Dify application configuration."""

    app_name: str = "cad3dify"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8780
    cors_origins: list[str] = ["http://localhost:3001"]

    # Security / sandbox
    api_key: str | None = None
    max_concurrent_executions: int = 4
    execution_timeout_s: int = 60
    execution_memory_mb: int = 2048

    # Organic engine
    organic_enabled: bool = True
    tripo3d_api_key: str | None = None
    hunyuan3d_api_key: str | None = None
    organic_default_provider: str = "auto"  # "auto" | "tripo3d" | "hunyuan3d"
    organic_upload_max_mb: int = 10

    model_config = {"env_file": ".env", "extra": "ignore"}
