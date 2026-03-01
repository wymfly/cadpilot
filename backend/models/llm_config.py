"""LLM role configuration — defines available roles with default models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# All recognized LLM role identifiers.
LLMRole = Literal[
    "intent_parser",
    "vision_analyzer",
    "code_generator",
    "refiner_vl",
    "refiner_coder",
    "organic_spec",
]


@dataclass(frozen=True)
class RoleConfig:
    """Single LLM role configuration."""

    role: str
    display_name: str  # Chinese display name for UI
    group: str  # "precision" or "organic"
    default_model: str  # MODEL_TYPE name
    default_temp: float


# Built-in defaults — always available as fallback.
DEFAULT_ROLES: dict[str, RoleConfig] = {
    "intent_parser": RoleConfig(
        "intent_parser", "意图解析", "precision", "qwen", 1.0
    ),
    "vision_analyzer": RoleConfig(
        "vision_analyzer", "图纸分析", "precision", "qwen-vl", 0.1
    ),
    "code_generator": RoleConfig(
        "code_generator", "代码生成", "precision", "qwen-coder", 0.3
    ),
    "refiner_vl": RoleConfig(
        "refiner_vl", "修复-视觉", "precision", "qwen-vl", 0.1
    ),
    "refiner_coder": RoleConfig(
        "refiner_coder", "修复-代码", "precision", "qwen-coder", 0.3
    ),
    "organic_spec": RoleConfig(
        "organic_spec", "创意规格", "organic", "qwen", 0.1
    ),
}
