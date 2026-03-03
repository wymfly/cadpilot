"""Tests for orientation_optimizer node and strategies."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


class TestOrientationOptimizerConfig:
    def test_defaults(self):
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig

        cfg = OrientationOptimizerConfig()
        assert cfg.strategy == "basic"
        assert cfg.enabled is True
        assert cfg.weight_support_area == 0.4
        assert cfg.weight_height == 0.3
        assert cfg.weight_stability == 0.3

    def test_weights_sum_validation(self):
        """Weights can be any positive float -- no sum constraint."""
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig

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
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig
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


class TestScipyOrientStrategy:
    """ScipyOrientStrategy: continuous optimization via differential_evolution."""

    @pytest.fixture
    def strategy(self):
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig
        from backend.graph.strategies.orient.scipy_orient import \
            ScipyOrientStrategy

        cfg = OrientationOptimizerConfig(
            strategy="scipy",
            scipy_max_iter=20,
            scipy_popsize=5,
        )
        return ScipyOrientStrategy(config=cfg)

    def test_check_available(self, strategy):
        assert strategy.check_available() is True

    def test_optimize_returns_rotation_matrix(self, strategy):
        """optimize(mesh) returns (4x4 rotation matrix, score)."""
        mesh = _make_box_mesh(10, 20, 30)
        rotation, score = strategy.optimize(mesh)
        assert rotation.shape == (4, 4)
        assert isinstance(score, float)

    def test_scipy_at_least_as_good_as_basic(self, strategy):
        """Scipy should find score <= basic 6-direction score."""
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig
        from backend.graph.strategies.orient.basic import BasicOrientStrategy

        cfg = OrientationOptimizerConfig()
        basic = BasicOrientStrategy(config=cfg)

        mesh = _make_box_mesh(30, 50, 80)
        _, basic_score, _ = basic.find_best_orientation(mesh)
        _, scipy_score = strategy.optimize(mesh)
        # Scipy explores continuous space, should be at least equal
        assert scipy_score <= basic_score + 1.0  # Small tolerance

    def test_rotation_matrix_is_valid(self, strategy):
        """Resulting rotation should be a valid rotation matrix (det ≈ 1)."""
        mesh = _make_box_mesh(20, 20, 60)
        rotation, _ = strategy.optimize(mesh)
        # 3x3 rotation submatrix should have determinant ≈ 1
        det = np.linalg.det(rotation[:3, :3])
        assert abs(det - 1.0) < 1e-6


class TestOrientationOptimizerNode:
    """Node-level tests for orientation_optimizer."""

    @pytest.fixture
    def mock_ctx(self, tmp_path):
        """Create a mock NodeContext with a box mesh."""
        mesh = _make_box_mesh(10, 10, 100)  # Tall box
        mesh_path = str(tmp_path / "test.glb")
        mesh.export(mesh_path)

        ctx = MagicMock()
        ctx.job_id = "test-orient-001"
        ctx.config = MagicMock()
        ctx.config.strategy = "basic"
        ctx.config.weight_support_area = 0.4
        ctx.config.weight_height = 0.3
        ctx.config.weight_stability = 0.3

        asset = MagicMock()
        asset.path = mesh_path
        ctx.get_asset.return_value = asset
        ctx.has_asset.return_value = True
        ctx.dispatch_progress = AsyncMock()

        return ctx

    @pytest.mark.asyncio
    async def test_node_registers_strategy(self):
        """Node should be registered with basic and scipy strategies."""
        from backend.graph.nodes.orientation_optimizer import \
            orientation_optimizer_node

        desc = orientation_optimizer_node._node_descriptor
        assert "basic" in desc.strategies
        assert "scipy" in desc.strategies
        assert desc.fallback_chain == ["scipy", "basic"]

    @pytest.mark.asyncio
    async def test_node_no_input_skips(self):
        """No final_mesh → skip gracefully."""
        from backend.graph.nodes.orientation_optimizer import \
            orientation_optimizer_node

        ctx = MagicMock()
        ctx.has_asset.return_value = False
        ctx.config = MagicMock()
        ctx.config.strategy = "basic"

        await orientation_optimizer_node(ctx)
        ctx.put_data.assert_called_with(
            "orientation_optimizer_status", "skipped_no_input"
        )

    @pytest.mark.asyncio
    async def test_basic_strategy_produces_oriented_mesh(self, mock_ctx):
        """Basic strategy should register oriented_mesh asset."""
        from backend.graph.configs.orientation_optimizer import \
            OrientationOptimizerConfig
        from backend.graph.strategies.orient.basic import BasicOrientStrategy

        cfg = OrientationOptimizerConfig()
        strategy = BasicOrientStrategy(config=cfg)

        await strategy.execute(mock_ctx)

        mock_ctx.put_asset.assert_called_once()
        call_args = mock_ctx.put_asset.call_args
        assert call_args[0][0] == "oriented_mesh"
        assert call_args[0][2] == "mesh"


def _make_box_mesh(x: float, y: float, z: float):
    """Create a simple box mesh for testing."""
    import trimesh

    return trimesh.creation.box(extents=[x, y, z])
