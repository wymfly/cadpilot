"""Tests for SFT/GRPO training config and reward functions."""
import numpy as np
import pytest

from scripts.training.sft_config import SFTConfig, GRPOConfig, EvalMetrics
from scripts.training.grpo_reward import (
    chamfer_distance,
    geometric_reward,
)


class TestSFTConfig:
    def test_defaults(self):
        cfg = SFTConfig()
        assert cfg.base_model == "Qwen/Qwen2.5-Coder-7B"
        assert cfg.num_epochs == 3
        assert cfg.lora_rank == 16

    def test_custom_config(self):
        cfg = SFTConfig(base_model="Qwen/Qwen2.5-Coder-3B", num_epochs=5)
        assert cfg.base_model == "Qwen/Qwen2.5-Coder-3B"
        assert cfg.num_epochs == 5


class TestGRPOConfig:
    def test_defaults(self):
        cfg = GRPOConfig()
        assert cfg.reward_threshold == 1e-5
        assert cfg.group_size == 4


class TestChamferDistance:
    def test_identical_points(self):
        pts = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float64)
        cd = chamfer_distance(pts, pts)
        assert cd == pytest.approx(0.0)

    def test_different_points(self):
        a = np.array([[0, 0, 0]], dtype=np.float64)
        b = np.array([[1, 0, 0]], dtype=np.float64)
        cd = chamfer_distance(a, b)
        assert cd > 0

    def test_symmetric(self):
        rng = np.random.default_rng(42)
        a = rng.random((50, 3))
        b = rng.random((50, 3))
        assert chamfer_distance(a, b) == pytest.approx(chamfer_distance(b, a))

    def test_empty_input(self):
        a = np.array([], dtype=np.float64).reshape(0, 3)
        b = np.array([[1, 0, 0]], dtype=np.float64)
        assert chamfer_distance(a, b) == float("inf")

    def test_close_points_small_cd(self):
        a = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
        b = np.array([[0.001, 0, 0], [1.001, 0, 0]], dtype=np.float64)
        cd = chamfer_distance(a, b)
        assert cd < 1e-4


class TestGeometricReward:
    def test_perfect_match(self):
        r = geometric_reward(0.0)
        assert r == 1.0

    def test_at_threshold(self):
        r = geometric_reward(1e-5, threshold=1e-5)
        assert r == 1.0  # ≤ threshold → max

    def test_above_threshold_decays(self):
        r = geometric_reward(1e-3, threshold=1e-5)
        assert 0.0 < r < 1.0

    def test_very_large_cd(self):
        r = geometric_reward(1e6, threshold=1e-5)
        assert r == pytest.approx(0.0, abs=1e-10)

    def test_custom_max_reward(self):
        r = geometric_reward(0.0, max_reward=10.0)
        assert r == 10.0


class TestModelTypeIntegration:
    def test_qwen_ft_coder_registered(self):
        from backend.infra.chat_models import ChatModelParameters
        params = ChatModelParameters.from_model_name("qwen-ft-coder")
        assert params.model_name == "qwen-ft-coder-cadquery"
        assert params.temperature == 0.2

    def test_existing_models_unchanged(self):
        from backend.infra.chat_models import ChatModelParameters
        params = ChatModelParameters.from_model_name("qwen-coder")
        assert params.model_name == "qwen-coder-plus"
