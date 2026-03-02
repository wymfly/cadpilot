"""Pipeline presets — predefined configurations for common use cases."""

from __future__ import annotations

from typing import Any

# 每个预设定义哪些节点启用、用什么策略
PIPELINE_PRESETS: dict[str, dict[str, dict[str, Any]]] = {
    "fast": {
        "_meta": {"display_name": "快速模式", "description": "跳过非必要步骤，最快出结果"},
        "convert_preview": {"enabled": True},
        "check_printability": {"enabled": False},
        "analyze_dfam": {"enabled": False},
    },
    "balanced": {
        "_meta": {"display_name": "均衡模式", "description": "默认配置，兼顾速度和质量"},
        "convert_preview": {"enabled": True},
        "check_printability": {"enabled": True},
        "analyze_dfam": {"enabled": False},
    },
    "full_print": {
        "_meta": {"display_name": "打印就绪", "description": "完整分析，确保3D打印质量"},
        "convert_preview": {"enabled": True},
        "check_printability": {"enabled": True},
        "analyze_dfam": {"enabled": True},
    },
}


def parse_pipeline_config(
    raw_config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Parse user-provided pipeline config, expanding preset references.

    If raw_config contains {"preset": "fast"}, expand it from PIPELINE_PRESETS.
    Custom node overrides in raw_config take precedence over preset values.
    """
    preset_name = raw_config.pop("preset", None) if isinstance(raw_config, dict) else None

    if preset_name and preset_name in PIPELINE_PRESETS:
        base = {}
        for k, v in PIPELINE_PRESETS[preset_name].items():
            if k != "_meta":
                base[k] = dict(v)  # copy
        # Merge custom overrides
        for k, v in raw_config.items():
            if isinstance(v, dict):
                base.setdefault(k, {}).update(v)
        return base

    # No preset: return as-is (treat as node-level config)
    return {k: v for k, v in raw_config.items() if isinstance(v, dict)}
