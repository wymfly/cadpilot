"""Tests for pipeline presets and compatibility layer."""

from __future__ import annotations

import pytest

from backend.graph.presets import PIPELINE_PRESETS, parse_pipeline_config
from backend.graph.compat import convert_legacy_pipeline_config, is_legacy_format


# ---------------------------------------------------------------------------
# PIPELINE_PRESETS structure
# ---------------------------------------------------------------------------


class TestPipelinePresets:
    def test_all_presets_have_meta(self):
        for name, preset in PIPELINE_PRESETS.items():
            assert "_meta" in preset, f"Preset '{name}' missing _meta"
            assert "display_name" in preset["_meta"]
            assert "description" in preset["_meta"]

    def test_fast_disables_printability_and_dfam(self):
        fast = PIPELINE_PRESETS["fast"]
        assert fast["check_printability"]["enabled"] is False
        assert fast["analyze_dfam"]["enabled"] is False

    def test_balanced_enables_printability(self):
        bal = PIPELINE_PRESETS["balanced"]
        assert bal["check_printability"]["enabled"] is True
        assert bal["analyze_dfam"]["enabled"] is False

    def test_full_print_enables_everything(self):
        fp = PIPELINE_PRESETS["full_print"]
        assert fp["convert_preview"]["enabled"] is True
        assert fp["check_printability"]["enabled"] is True
        assert fp["analyze_dfam"]["enabled"] is True


# ---------------------------------------------------------------------------
# parse_pipeline_config
# ---------------------------------------------------------------------------


class TestParsePipelineConfig:
    def test_expand_preset(self):
        raw = {"preset": "fast"}
        result = parse_pipeline_config(raw)
        # _meta should be excluded
        assert "_meta" not in result
        assert result["check_printability"]["enabled"] is False

    def test_preset_with_override(self):
        raw = {"preset": "fast", "check_printability": {"enabled": True}}
        result = parse_pipeline_config(raw)
        # Override takes precedence
        assert result["check_printability"]["enabled"] is True

    def test_unknown_preset_ignored(self):
        raw = {"preset": "nonexistent", "my_node": {"enabled": True}}
        result = parse_pipeline_config(raw)
        assert "my_node" in result
        assert result["my_node"]["enabled"] is True

    def test_no_preset_passthrough(self):
        raw = {"node_a": {"enabled": True}, "node_b": {"strategy": "fast"}}
        result = parse_pipeline_config(raw)
        assert result == {"node_a": {"enabled": True}, "node_b": {"strategy": "fast"}}

    def test_non_dict_values_filtered(self):
        raw = {"node_a": {"enabled": True}, "stray_key": "string_value"}
        result = parse_pipeline_config(raw)
        assert "stray_key" not in result
        assert "node_a" in result

    def test_empty_config(self):
        result = parse_pipeline_config({})
        assert result == {}

    def test_preset_does_not_mutate_original(self):
        """Ensure expanding a preset doesn't modify PIPELINE_PRESETS."""
        import copy

        original = copy.deepcopy(PIPELINE_PRESETS["fast"])
        parse_pipeline_config({"preset": "fast", "convert_preview": {"extra": True}})
        assert PIPELINE_PRESETS["fast"] == original


# ---------------------------------------------------------------------------
# is_legacy_format
# ---------------------------------------------------------------------------


class TestIsLegacyFormat:
    def test_empty_is_not_legacy(self):
        assert is_legacy_format({}) is False

    def test_all_dicts_is_new(self):
        assert is_legacy_format({"node_a": {"enabled": True}}) is False

    def test_string_value_is_legacy(self):
        assert is_legacy_format({"preset": "balanced"}) is True

    def test_bool_value_is_legacy(self):
        assert is_legacy_format({"enable_dfam": True}) is True

    def test_mixed_is_legacy(self):
        assert is_legacy_format({"enable_dfam": True, "node_a": {"x": 1}}) is True


# ---------------------------------------------------------------------------
# convert_legacy_pipeline_config
# ---------------------------------------------------------------------------


class TestConvertLegacyPipelineConfig:
    def test_preset_expansion(self):
        result = convert_legacy_pipeline_config({"preset": "balanced"})
        assert "convert_preview" in result
        assert result["check_printability"]["enabled"] is True

    def test_enable_dfam(self):
        result = convert_legacy_pipeline_config({"enable_dfam": True})
        assert result["analyze_dfam"]["enabled"] is True

    def test_disable_dfam(self):
        result = convert_legacy_pipeline_config({"enable_dfam": False})
        assert result["analyze_dfam"]["enabled"] is False

    def test_enable_printability(self):
        result = convert_legacy_pipeline_config({"enable_printability": True})
        assert result["check_printability"]["enabled"] is True

    def test_precise_strategy(self):
        result = convert_legacy_pipeline_config({"generate_model": "precise"})
        assert result["analyze_intent"]["strategy"] == "two_pass"

    def test_non_precise_model_no_strategy(self):
        result = convert_legacy_pipeline_config({"generate_model": "fast"})
        assert "analyze_intent" not in result

    def test_preset_plus_overrides(self):
        result = convert_legacy_pipeline_config({
            "preset": "fast",
            "enable_dfam": True,
        })
        # fast disables dfam, but explicit override wins
        assert result["analyze_dfam"]["enabled"] is True

    def test_empty_legacy(self):
        result = convert_legacy_pipeline_config({})
        assert result == {}

    def test_unknown_preset_ignored(self):
        result = convert_legacy_pipeline_config({"preset": "nonexistent"})
        assert result == {}
