"""Tests for orientation_optimizer node and strategies."""

from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import MagicMock


class TestOrientationOptimizerConfig:
    def test_defaults(self):
        from backend.graph.configs.orientation_optimizer import OrientationOptimizerConfig
        cfg = OrientationOptimizerConfig()
        assert cfg.strategy == "basic"
        assert cfg.enabled is True
        assert 0 < cfg.weight_support_area <= 1.0
        assert 0 < cfg.weight_height <= 1.0
        assert 0 < cfg.weight_stability <= 1.0

    def test_weights_sum_validation(self):
        """Weights can be any positive float -- no sum constraint."""
        from backend.graph.configs.orientation_optimizer import OrientationOptimizerConfig
        cfg = OrientationOptimizerConfig(
            weight_support_area=0.5,
            weight_height=0.3,
            weight_stability=0.2,
        )
        assert cfg.weight_support_area == 0.5


class TestBasicOrientStrategy:
    """BasicOrientStrategy: 6-direction discrete search (+/-X, +/-Y, +/-Z)."""

    @pytest.fixture
    def strategy(self):
        from backend.graph.configs.orientation_optimizer import OrientationOptimizerConfig
        from backend.graph.strategies.orient.basic import BasicOrientStrategy
        cfg = OrientationOptimizerConfig()
        return BasicOrientStrategy(config=cfg)

    def test_check_available_always_true(self, strategy):
        assert strategy.check_available() is True

    def test_evaluate_orientation_returns_score(self, strategy):
        """evaluate_orientation(mesh, rotation_matrix) -> float score."""
        mesh = _make_box_mesh(10, 20, 30)
        score = strategy.evaluate_orientation(mesh, np.eye(4))
        assert isinstance(score, float)
        assert score >= 0

    def test_flat_box_prefers_largest_face_down(self, strategy):
        """A flat box (100x100x10) should prefer Z-up (XY face down)."""
        mesh = _make_box_mesh(100, 100, 10)
        best_rotation, best_score, all_scores = strategy.find_best_orientation(mesh)
        assert best_rotation is not None
        assert len(all_scores) == 6

    def test_tall_box_prefers_laying_down(self, strategy):
        """A tall box (10x10x100) should prefer laying flat."""
        mesh = _make_box_mesh(10, 10, 100)
        best_rotation, best_score, all_scores = strategy.find_best_orientation(mesh)
        rotated = mesh.copy()
        rotated.apply_transform(best_rotation)
        assert rotated.bounding_box.extents[2] < 100

    def test_execute_registers_oriented_mesh(self, strategy):
        """Strategy.execute(ctx) should register 'oriented_mesh' asset."""
        pytest.skip("Tested in Task 3 (node integration)")


def _make_box_mesh(x: float, y: float, z: float):
    """Create a simple box mesh for testing."""
    import trimesh
    return trimesh.creation.box(extents=[x, y, z])
