"""Tests for thermal_simulation node (degraded to DfAM thermal risk report)."""

from __future__ import annotations

import numpy as np
import pytest


class TestThermalSimulationConfig:
    def test_defaults(self):
        from backend.graph.configs.thermal_simulation import \
            ThermalSimulationConfig

        cfg = ThermalSimulationConfig()
        assert cfg.strategy == "rules"
        assert cfg.overhang_threshold == 45.0
        assert cfg.aspect_ratio_threshold == 10.0

    def test_overhang_threshold_validation(self):
        from backend.graph.configs.thermal_simulation import \
            ThermalSimulationConfig

        with pytest.raises(ValueError):
            ThermalSimulationConfig(overhang_threshold=-1)


class TestRulesThermalStrategy:
    """Rules-based thermal risk assessment from geometry features."""

    @pytest.fixture
    def strategy(self):
        from backend.graph.configs.thermal_simulation import \
            ThermalSimulationConfig
        from backend.graph.strategies.thermal.rules import RulesThermalStrategy

        cfg = ThermalSimulationConfig()
        return RulesThermalStrategy(config=cfg)

    def test_check_available(self, strategy):
        assert strategy.check_available() is True

    def test_analyze_returns_thermal_report(self, strategy):
        """analyze(mesh) returns a ThermalRiskReport dict."""
        import trimesh

        mesh = trimesh.creation.box(extents=[10, 10, 50])
        report = strategy.analyze(mesh)
        assert "risk_level" in report
        assert report["risk_level"] in ("low", "medium", "high")
        assert "risk_factors" in report
        assert isinstance(report["risk_factors"], list)

    def test_tall_thin_part_gets_high_risk(self, strategy):
        """A tall thin part (2x2x100) should have high thermal risk."""
        import trimesh

        mesh = trimesh.creation.box(extents=[2, 2, 100])
        report = strategy.analyze(mesh)
        assert report["risk_level"] in ("medium", "high")
        assert any(
            "高宽比" in f["description"] or "aspect" in f["description"].lower()
            for f in report["risk_factors"]
        )

    def test_cube_gets_low_risk(self, strategy):
        """A simple cube should have low thermal risk."""
        import trimesh

        mesh = trimesh.creation.box(extents=[20, 20, 20])
        report = strategy.analyze(mesh)
        assert report["risk_level"] == "low"

    def test_report_includes_recommendations(self, strategy):
        """Report should include actionable recommendations."""
        import trimesh

        mesh = trimesh.creation.box(extents=[2, 2, 100])
        report = strategy.analyze(mesh)
        assert "recommendations" in report
        assert len(report["recommendations"]) > 0
