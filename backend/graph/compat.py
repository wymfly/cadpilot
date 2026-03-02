"""Compatibility layer — convert old PipelineConfig format to new format."""

from __future__ import annotations

from typing import Any


def convert_legacy_pipeline_config(
    legacy: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Convert old-style PipelineConfig.model_dump() to new per-node config.

    Old format:
        {"generate_model": "precise", "enable_dfam": True, "preset": "balanced", ...}

    New format:
        {"analyze_dfam": {"enabled": True}, "analyze_intent": {"strategy": "two_pass"}, ...}
    """
    new_config: dict[str, dict[str, Any]] = {}

    # Map old preset to new preset
    preset = legacy.get("preset")
    if preset:
        from backend.graph.presets import PIPELINE_PRESETS

        if preset in PIPELINE_PRESETS:
            for k, v in PIPELINE_PRESETS[preset].items():
                if k != "_meta":
                    new_config[k] = dict(v)

    # Map specific old fields to new node configs
    if legacy.get("enable_dfam") is not None:
        new_config.setdefault("analyze_dfam", {})["enabled"] = legacy["enable_dfam"]

    if legacy.get("enable_printability") is not None:
        new_config.setdefault("check_printability", {})["enabled"] = legacy[
            "enable_printability"
        ]

    if legacy.get("generate_model") == "precise":
        new_config.setdefault("analyze_intent", {})["strategy"] = "two_pass"

    return new_config


def is_legacy_format(config: dict[str, Any]) -> bool:
    """Detect if a pipeline_config is in old format.

    Old format has top-level string/bool values.
    New format has top-level dict values (node configs).
    """
    if not config:
        return False
    # If any top-level value is not a dict, it's legacy
    return any(not isinstance(v, dict) for v in config.values())
