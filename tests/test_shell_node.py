"""Tests for shell_node — passthrough and shell modes."""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestShellNodeConfig:

    def test_defaults(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        config = ShellNodeConfig()
        assert config.shell_enabled is False
        assert config.wall_thickness == 2.0
        assert config.voxel_resolution == 0  # adaptive
        assert config.strategy == "meshlib"

    def test_wall_thickness_must_be_positive(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        with pytest.raises(Exception):  # ValidationError
            ShellNodeConfig(wall_thickness=0)

    def test_wall_thickness_max_50(self):
        from backend.graph.configs.shell_node import ShellNodeConfig
        with pytest.raises(Exception):
            ShellNodeConfig(wall_thickness=51)


class TestShellNodePassthrough:

    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self):
        """shell_enabled=False -> scaled_mesh passed through as shelled_mesh."""
        from backend.graph.nodes.shell_node import shell_node_fn

        ctx = MagicMock()
        ctx.config = MagicMock(shell_enabled=False)
        mock_asset = MagicMock(path="/tmp/scaled.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.has_asset.return_value = True

        await shell_node_fn(ctx)

        ctx.put_asset.assert_called_once()
        call_args = ctx.put_asset.call_args
        assert call_args[0][0] == "shelled_mesh"  # asset key
        assert call_args[0][1] == "/tmp/scaled.glb"  # same path = passthrough


class TestShellNodeFailure:

    @pytest.mark.asyncio
    async def test_failure_raises_not_silent(self):
        """non_fatal=False -> shell failure raises exception."""
        from backend.graph.strategies.shell.meshlib_shell import MeshLibShellStrategy

        strategy = MeshLibShellStrategy(
            config=MagicMock(wall_thickness=2.0, voxel_resolution=256)
        )
        ctx = MagicMock()
        ctx.job_id = "test"
        mock_asset = MagicMock(path="/tmp/nonexistent.glb")
        ctx.get_asset.return_value = mock_asset
        ctx.dispatch_progress = AsyncMock()

        with pytest.raises(Exception):
            await strategy.execute(ctx)


class TestAdaptiveResolution:

    def test_resolution_formula(self):
        """Verify adaptive resolution: min(512, max(256, ceil(bbox_max / wall_thickness * 5)))."""
        from backend.graph.strategies.shell.meshlib_shell import _compute_adaptive_resolution

        # Small object: 50mm bbox, 2mm wall -> ceil(50/2*5) = 125 -> clamped to 256
        assert _compute_adaptive_resolution(50.0, 2.0) == 256

        # Medium: 200mm bbox, 2mm wall -> ceil(200/2*5) = 500 -> 500
        assert _compute_adaptive_resolution(200.0, 2.0) == 500

        # Large: 500mm bbox, 1mm wall -> ceil(500/1*5) = 2500 -> clamped to 512
        assert _compute_adaptive_resolution(500.0, 1.0) == 512
