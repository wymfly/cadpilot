"""LLM configuration manager — role-based model selection.

Reads user overrides from YAML, falls back to built-in defaults.
Module-level cache for performance.
"""

from __future__ import annotations

import typing
from pathlib import Path

import yaml

from backend.infra.chat_models import MODEL_TYPE, ChatModelParameters
from backend.models.llm_config import DEFAULT_ROLES, RoleConfig

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "knowledge" / "llm_config.yaml"
)
_cache: dict[str, str] | None = None  # role -> model_name overrides


def _load_overrides() -> dict[str, str]:
    """Load YAML overrides, return empty dict if file missing."""
    global _cache
    if _cache is not None:
        return _cache
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}
        _cache = data.get("roles", {})
    else:
        _cache = {}
    return _cache


def invalidate_cache() -> None:
    """Clear cached overrides — call after writing new config."""
    global _cache
    _cache = None


def get_model_for_role(role: str) -> ChatModelParameters:
    """Get ChatModelParameters for a role (YAML override -> default).

    Raises ``ValueError`` for unknown role names.
    """
    overrides = _load_overrides()
    role_config: RoleConfig | None = DEFAULT_ROLES.get(role)
    if role_config is None:
        raise ValueError(f"Unknown LLM role: {role}")
    model_name = overrides.get(role, role_config.default_model)
    return ChatModelParameters.from_model_name(model_name)


def get_current_config() -> dict[str, dict]:
    """Get full config for API response (all roles with current model)."""
    overrides = _load_overrides()
    result: dict[str, dict] = {}
    for role, rc in DEFAULT_ROLES.items():
        result[role] = {
            "role": role,
            "display_name": rc.display_name,
            "group": rc.group,
            "default_model": rc.default_model,
            "default_temp": rc.default_temp,
            "current_model": overrides.get(role, rc.default_model),
        }
    return result


def save_config(roles: dict[str, str]) -> None:
    """Save role overrides to YAML and invalidate cache."""
    # Validate model names before persisting
    valid_models = {m for m in get_available_model_names()}
    for role, model in roles.items():
        if role not in DEFAULT_ROLES:
            raise ValueError(f"Unknown LLM role: {role}")
        if model not in valid_models:
            raise ValueError(
                f"Unknown model type '{model}' for role '{role}'"
            )

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        yaml.dump({"roles": roles}, f, allow_unicode=True)
    invalidate_cache()


def get_available_model_names() -> list[str]:
    """Return the list of valid MODEL_TYPE literal values."""
    return list(typing.get_args(MODEL_TYPE))


def get_available_models() -> list[dict[str, str]]:
    """Return list of available MODEL_TYPEs with display names."""
    display_map: dict[str, str] = {
        "gpt": "GPT (OpenAI)",
        "claude": "Claude (Anthropic)",
        "gemini": "Gemini (Google)",
        "llama": "Llama (Meta)",
        "qwen": "Qwen (通义千问)",
        "qwen-vl": "Qwen-VL (通义千问视觉)",
        "qwen-coder": "Qwen-Coder (通义千问代码)",
        "qwen-ft-coder": "Qwen-FT-Coder (微调代码)",
    }
    return [
        {"name": m, "display_name": display_map.get(m, m)}
        for m in get_available_model_names()
    ]
