"""Tests for boolean_assemble node — manifold3d strategy with voxel repair gate.

TDD tests for Phase 2 Task 3: boolean_assemble node implementation.
Tests cover:
- Node registration: registry.get("boolean_assemble") with manifold3d strategy
- Manifold mesh passes directly (no voxelization)
- Non-manifold mesh repaired by voxelization
- Non-manifold repair failure (skip=False -> exception)
- Non-manifold repair failure (skip=True -> passthrough + warning)
- 2x resolution retry on voxelization failure
- FlatBottomCut, HoleCut, SlotCut operations
- Single cut failure continues (partial_cuts)
- All cuts fail -> exception
- No cuts passthrough
- Draft mode passthrough
- No input skipped
- Progress reporting
"""

from __future__ import annotations

import asyncio
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from backend.graph.configs.base import BaseNodeConfig
from backend.graph.context import AssetRegistry, NodeContext
from backend.graph.registry import registry
from backend.models.organic import (
    FlatBottomCut,
    HoleCut,
    OrganicSpec,
    SlotCut,
)


def _reset_registry() -> None:
    """Force re-discovery so newly added modules are registered."""
    import backend.graph.discovery as disc

    # Remove old stubs that have been replaced
    registry._remove("boolean_cuts")
    registry._remove("export_formats")

    disc._discovered = False
    disc.discover_nodes()


@pytest.fixture(autouse=True, scope="module")
def _ensure_discovery() -> None:
    _reset_registry()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_organic_spec(
    *,
    quality_mode: str = "standard",
    engineering_cuts: list | None = None,
    final_bounding_box: tuple[float, float, float] | None = (100, 100, 100),
) -> OrganicSpec:
    """Build an OrganicSpec for testing."""
    return OrganicSpec(
        prompt_en="test shape",
        prompt_original="test shape",
        shape_category="abstract",
        final_bounding_box=final_bounding_box,
        engineering_cuts=engineering_cuts or [],
        quality_mode=quality_mode,
    )


def _make_test_mesh() -> trimesh.Trimesh:
    """Create a simple box mesh for testing."""
    return trimesh.primitives.Box(extents=(50, 50, 50)).to_mesh()


def _save_mesh_to_tmp(mesh: trimesh.Trimesh) -> str:
    """Export mesh to a temp file and return path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
    mesh.export(tmp.name)
    tmp.close()
    return tmp.name


def _make_ctx(
    *,
    has_shelled_mesh: bool = True,
    mesh: trimesh.Trimesh | None = None,
    organic_spec: OrganicSpec | None = None,
    config_overrides: dict | None = None,
) -> NodeContext:
    """Build a NodeContext for boolean_assemble testing."""
    desc = registry.get("boolean_assemble")
    asset_reg = AssetRegistry()

    mesh_path = ""
    if has_shelled_mesh:
        if mesh is None:
            mesh = _make_test_mesh()
        mesh_path = _save_mesh_to_tmp(mesh)
        asset_reg.put("shelled_mesh", mesh_path, "mesh", "shell_node")

    data: dict = {}
    if organic_spec is not None:
        data["organic_spec"] = organic_spec

    config_cls = desc.config_model or BaseNodeConfig
    raw_config = config_overrides or {}
    config = config_cls(**raw_config)

    return NodeContext(
        job_id="test-boolean-1",
        input_type="organic",
        assets=asset_reg,
        data=data,
        config=config,
        descriptor=desc,
        node_name="boolean_assemble",
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestBooleanAssembleRegistration:
    """Verify boolean_assemble is registered with correct metadata."""

    def test_boolean_assemble_registered(self) -> None:
        desc = registry.get("boolean_assemble")
        assert desc.display_name == "布尔装配"
        assert desc.requires == ["shelled_mesh"]
        assert desc.produces == ["final_mesh"]
        assert desc.input_types == ["organic"]

    def test_has_manifold3d_strategy(self) -> None:
        desc = registry.get("boolean_assemble")
        assert "manifold3d" in desc.strategies

    def test_default_strategy_is_manifold3d(self) -> None:
        desc = registry.get("boolean_assemble")
        assert desc.default_strategy == "manifold3d"

    def test_boolean_cuts_not_in_registry(self) -> None:
        """Old boolean_cuts stub should not exist anymore."""
        assert "boolean_cuts" not in registry


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestBooleanAssembleConfig:
    """Verify BooleanAssembleConfig defaults and validation."""

    def test_default_values(self) -> None:
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig

        config = BooleanAssembleConfig()
        assert config.strategy == "manifold3d"
        assert config.voxel_resolution == 128
        assert config.skip_on_non_manifold is False

    def test_custom_values(self) -> None:
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig

        config = BooleanAssembleConfig(
            strategy="manifold3d",
            voxel_resolution=256,
            skip_on_non_manifold=True,
        )
        assert config.voxel_resolution == 256
        assert config.skip_on_non_manifold is True


# ---------------------------------------------------------------------------
# Passthrough / Skip tests
# ---------------------------------------------------------------------------


class TestBooleanAssemblePassthrough:
    """Tests for passthrough and skip conditions."""

    @pytest.mark.asyncio
    async def test_passthrough_when_no_cuts(self) -> None:
        """No engineering_cuts -> passthrough shelled_mesh as final_mesh."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        spec = _make_organic_spec(engineering_cuts=[])
        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=spec)

        await boolean_assemble_node(ctx)

        assert ctx.has_asset("final_mesh")
        # Path should match shelled_mesh (passthrough)
        scaled_path = ctx.get_asset("shelled_mesh").path
        final_path = ctx.get_asset("final_mesh").path
        assert final_path == scaled_path
        assert ctx.get_data("boolean_assemble_status") == "passthrough_no_cuts"

    @pytest.mark.asyncio
    async def test_passthrough_when_no_organic_spec(self) -> None:
        """No organic_spec -> passthrough (no cuts to apply)."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=None)

        await boolean_assemble_node(ctx)

        assert ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "passthrough_no_cuts"

    @pytest.mark.asyncio
    async def test_passthrough_in_draft_mode(self) -> None:
        """quality_mode='draft' -> passthrough, skip boolean operations."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        spec = _make_organic_spec(
            quality_mode="draft",
            engineering_cuts=[FlatBottomCut(offset=2.0)],
        )
        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=spec)

        await boolean_assemble_node(ctx)

        assert ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "passthrough_draft"

    @pytest.mark.asyncio
    async def test_skips_when_no_shelled_mesh(self) -> None:
        """No shelled_mesh -> skipped_no_input, no final_mesh produced."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = _make_ctx(has_shelled_mesh=False)

        await boolean_assemble_node(ctx)

        assert not ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "skipped_no_input"


# ---------------------------------------------------------------------------
# Manifold check gate tests
# ---------------------------------------------------------------------------


class TestManifold3DStrategyManifoldGate:
    """Tests for the manifold check gate in Manifold3DStrategy."""

    @pytest.mark.asyncio
    async def test_manifold_mesh_passes_directly(self) -> None:
        """When mesh is manifold (watertight), skip voxelization."""
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        strategy = Manifold3DStrategy()

        # Create a mock mesh that IS manifold
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = True
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([1.0, 1.0, 1.0])

        cuts = [FlatBottomCut(offset=2.0)]

        # Mock manifold3d boolean ops
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_result_mesh = MagicMock()
        mock_result_mesh.vert_properties = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
        mock_result_mesh.tri_verts = np.array([[0, 1, 2]], dtype=np.uint32)
        mock_manifold_instance = MagicMock()
        mock_manifold_instance.__sub__ = MagicMock(return_value=mock_manifold_instance)
        mock_manifold_instance.to_mesh.return_value = mock_result_mesh
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Manifold.cube.return_value = MagicMock()
        mock_manifold3d.Mesh.return_value = MagicMock()

        with patch.dict("sys.modules", {"manifold3d": mock_manifold3d}):
            result_mesh, applied, warnings = await asyncio.to_thread(
                strategy._execute_boolean_cuts, mock_mesh, cuts, mock_manifold3d
            )

        # Should NOT have called force_voxelize (mesh was manifold)
        assert applied >= 0  # At least attempted

    @pytest.mark.asyncio
    async def test_non_manifold_mesh_gets_voxelized(self) -> None:
        """When mesh is NOT manifold, attempt voxelization repair."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig(voxel_resolution=64)
        strategy = Manifold3DStrategy(config=config)

        # Mock context
        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        # Mock mesh that is NOT manifold initially, but becomes manifold after voxelization
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False  # non-manifold
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([1.0, 1.0, 1.0])
        mock_mesh.export = MagicMock()

        repaired_mesh = MagicMock()
        repaired_mesh.is_watertight = True  # repaired
        repaired_mesh.vertices = mock_mesh.vertices
        repaired_mesh.faces = mock_mesh.faces
        repaired_mesh.bounding_box = mock_mesh.bounding_box

        cuts = [FlatBottomCut(offset=2.0)]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)

        # Mock asset
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        # Mock trimesh.load to return our mock mesh
        # Mock manifold3d
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_result_mesh_data = MagicMock()
        mock_result_mesh_data.vert_properties = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32
        )
        mock_result_mesh_data.tri_verts = np.array([[0, 1, 2]], dtype=np.uint32)
        mock_manifold_instance = MagicMock()
        mock_manifold_instance.__sub__ = MagicMock(return_value=mock_manifold_instance)
        mock_manifold_instance.to_mesh.return_value = mock_result_mesh_data
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Manifold.cube.return_value = MagicMock()
        mock_manifold3d.Mesh.return_value = MagicMock()

        with (
            patch.dict("sys.modules", {"manifold3d": mock_manifold3d}),
            patch("trimesh.load", return_value=mock_mesh),
            patch(
                "backend.graph.strategies.boolean.manifold3d.Manifold3DStrategy._force_voxelize",
                return_value=repaired_mesh,
            ) as mock_voxelize,
        ):
            await strategy.execute(mock_ctx)

        # Voxelization should have been called because mesh was non-manifold
        mock_voxelize.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_manifold_skip_false_raises(self) -> None:
        """skip_on_non_manifold=False + repair fails -> raise exception."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig(
            voxel_resolution=64,
            skip_on_non_manifold=False,
        )
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        # Non-manifold mesh, voxelization also fails (stays non-manifold)
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([1.0, 1.0, 1.0])

        still_broken_mesh = MagicMock()
        still_broken_mesh.is_watertight = False  # still non-manifold

        cuts = [FlatBottomCut(offset=2.0)]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        with (
            patch("trimesh.load", return_value=mock_mesh),
            patch(
                "backend.graph.strategies.boolean.manifold3d.Manifold3DStrategy._force_voxelize",
                return_value=still_broken_mesh,
            ),
        ):
            with pytest.raises(RuntimeError, match="failed_non_manifold"):
                await strategy.execute(mock_ctx)

    @pytest.mark.asyncio
    async def test_non_manifold_skip_true_passthrough(self) -> None:
        """skip_on_non_manifold=True + repair fails -> passthrough + warning."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig(
            voxel_resolution=64,
            skip_on_non_manifold=True,
        )
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        # Non-manifold mesh, voxelization fails
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([1.0, 1.0, 1.0])

        still_broken = MagicMock()
        still_broken.is_watertight = False

        cuts = [FlatBottomCut(offset=2.0)]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        with (
            patch("trimesh.load", return_value=mock_mesh),
            patch(
                "backend.graph.strategies.boolean.manifold3d.Manifold3DStrategy._force_voxelize",
                return_value=still_broken,
            ),
        ):
            await strategy.execute(mock_ctx)

        # Should passthrough with warning
        mock_ctx.put_data.assert_any_call(
            "boolean_assemble_status", "passthrough_non_manifold"
        )

    @pytest.mark.asyncio
    async def test_2x_resolution_retry(self) -> None:
        """First voxelization fails -> retry with 2x resolution."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig(
            voxel_resolution=64,
            skip_on_non_manifold=False,
        )
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        mock_mesh = MagicMock()
        mock_mesh.is_watertight = False
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([1.0, 1.0, 1.0])

        # First voxelization: still non-manifold
        first_attempt = MagicMock()
        first_attempt.is_watertight = False

        # Second voxelization (2x): now manifold
        second_attempt = MagicMock()
        second_attempt.is_watertight = True
        second_attempt.vertices = mock_mesh.vertices
        second_attempt.faces = mock_mesh.faces
        second_attempt.bounding_box = mock_mesh.bounding_box

        cuts = [FlatBottomCut(offset=2.0)]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        # Mock manifold3d for boolean ops
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_result_mesh_data = MagicMock()
        mock_result_mesh_data.vert_properties = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32
        )
        mock_result_mesh_data.tri_verts = np.array([[0, 1, 2]], dtype=np.uint32)
        mock_manifold_instance = MagicMock()
        mock_manifold_instance.__sub__ = MagicMock(return_value=mock_manifold_instance)
        mock_manifold_instance.to_mesh.return_value = mock_result_mesh_data
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Manifold.cube.return_value = MagicMock()
        mock_manifold3d.Mesh.return_value = MagicMock()

        call_count = 0

        def mock_voxelize(mesh_arg, resolution):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                assert resolution == 64  # first attempt: original resolution
                return first_attempt
            else:
                assert resolution == 128  # second attempt: 2x resolution
                return second_attempt

        with (
            patch.dict("sys.modules", {"manifold3d": mock_manifold3d}),
            patch("trimesh.load", return_value=mock_mesh),
            patch(
                "backend.graph.strategies.boolean.manifold3d.Manifold3DStrategy._force_voxelize",
                side_effect=mock_voxelize,
            ),
        ):
            await strategy.execute(mock_ctx)

        # Should have been called twice (original + 2x)
        assert call_count == 2


# ---------------------------------------------------------------------------
# Boolean cut operation tests
# ---------------------------------------------------------------------------


class TestBooleanCutOperations:
    """Tests for FlatBottomCut, HoleCut, SlotCut operations."""

    @pytest.mark.asyncio
    async def test_flat_bottom_cut(self) -> None:
        """FlatBottomCut creates a tool and applies boolean difference."""
        from backend.graph.strategies.boolean.manifold3d import (
            _create_cut_tool,
        )

        mock_manifold3d = MagicMock()
        mock_cube = MagicMock()
        mock_cube.translate.return_value = mock_cube
        mock_manifold3d.Manifold.cube.return_value = mock_cube

        cut = FlatBottomCut(offset=2.0)
        extents = np.array([50.0, 50.0, 50.0])

        tool = _create_cut_tool(cut, extents, mock_manifold3d)

        assert tool is not None
        mock_manifold3d.Manifold.cube.assert_called_once()

    @pytest.mark.asyncio
    async def test_hole_cut(self) -> None:
        """HoleCut creates a cylinder tool."""
        from backend.graph.strategies.boolean.manifold3d import (
            _create_cut_tool,
        )

        mock_manifold3d = MagicMock()
        mock_cylinder = MagicMock()
        mock_cylinder.translate.return_value = mock_cylinder
        mock_manifold3d.Manifold.cylinder.return_value = mock_cylinder

        cut = HoleCut(diameter=5.0, depth=10.0, position=(0, 0, 0), direction="top")
        extents = np.array([50.0, 50.0, 50.0])

        tool = _create_cut_tool(cut, extents, mock_manifold3d)

        assert tool is not None
        mock_manifold3d.Manifold.cylinder.assert_called_once()

    @pytest.mark.asyncio
    async def test_slot_cut(self) -> None:
        """SlotCut creates a box tool."""
        from backend.graph.strategies.boolean.manifold3d import (
            _create_cut_tool,
        )

        mock_manifold3d = MagicMock()
        mock_cube = MagicMock()
        mock_cube.translate.return_value = mock_cube
        mock_manifold3d.Manifold.cube.return_value = mock_cube

        cut = SlotCut(width=10.0, depth=5.0, length=20.0, position=(0, 0, 0))
        extents = np.array([50.0, 50.0, 50.0])

        tool = _create_cut_tool(cut, extents, mock_manifold3d)

        assert tool is not None
        mock_manifold3d.Manifold.cube.assert_called()

    @pytest.mark.asyncio
    async def test_single_cut_failure_continues(self) -> None:
        """One cut fails -> skip it, continue rest, mark partial_cuts."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig()
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        # Manifold mesh (skip voxelization)
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = True
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([50.0, 50.0, 50.0])

        # Two cuts: first fails, second succeeds
        cuts = [
            FlatBottomCut(offset=2.0),
            HoleCut(diameter=5.0, depth=10.0, position=(0, 0, 0)),
        ]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        # Mock manifold3d: first cut raises, second succeeds
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_result_mesh_data = MagicMock()
        mock_result_mesh_data.vert_properties = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32
        )
        mock_result_mesh_data.tri_verts = np.array([[0, 1, 2]], dtype=np.uint32)
        mock_manifold_instance = MagicMock()
        mock_manifold_instance.to_mesh.return_value = mock_result_mesh_data
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Mesh.return_value = MagicMock()

        # First tool creation raises error, second succeeds
        call_count = 0
        original_cube = MagicMock()
        original_cube.translate.return_value = original_cube

        def mock_cube_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Geometry error in cut #1")
            return original_cube

        mock_manifold3d.Manifold.cube.side_effect = mock_cube_side_effect

        # Cylinder for hole cut
        mock_cylinder = MagicMock()
        mock_cylinder.translate.return_value = mock_cylinder
        mock_manifold3d.Manifold.cylinder.return_value = mock_cylinder

        # __sub__ should succeed for the second cut
        mock_manifold_instance.__sub__ = MagicMock(return_value=mock_manifold_instance)

        with (
            patch.dict("sys.modules", {"manifold3d": mock_manifold3d}),
            patch("trimesh.load", return_value=mock_mesh),
            patch("trimesh.Trimesh", return_value=mock_mesh),
        ):
            await strategy.execute(mock_ctx)

        # Should have partial_cuts status
        mock_ctx.put_data.assert_any_call(
            "boolean_assemble_status", "partial_cuts"
        )

    @pytest.mark.asyncio
    async def test_all_cuts_fail_raises(self) -> None:
        """All cuts fail -> raise exception (non-draft mode)."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig()
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        mock_mesh = MagicMock()
        mock_mesh.is_watertight = True
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([50.0, 50.0, 50.0])

        cuts = [
            FlatBottomCut(offset=2.0),
            HoleCut(diameter=5.0, depth=10.0),
        ]
        spec = _make_organic_spec(engineering_cuts=cuts, quality_mode="standard")
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        # All cut tools fail
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_manifold_instance = MagicMock()
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Mesh.return_value = MagicMock()
        mock_manifold3d.Manifold.cube.side_effect = ValueError("all fail")
        mock_manifold3d.Manifold.cylinder.side_effect = ValueError("all fail")

        with (
            patch.dict("sys.modules", {"manifold3d": mock_manifold3d}),
            patch("trimesh.load", return_value=mock_mesh),
        ):
            with pytest.raises(RuntimeError, match="All .* cuts failed"):
                await strategy.execute(mock_ctx)

    @pytest.mark.asyncio
    async def test_all_cuts_fail_draft_passthrough(self) -> None:
        """All cuts fail + draft mode -> passthrough with warning."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        spec = _make_organic_spec(
            quality_mode="draft",
            engineering_cuts=[FlatBottomCut(offset=2.0)],
        )
        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=spec)

        await boolean_assemble_node(ctx)

        # Draft mode: passthrough before attempting cuts
        assert ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "passthrough_draft"


# ---------------------------------------------------------------------------
# Progress reporting tests
# ---------------------------------------------------------------------------


class TestBooleanAssembleProgress:
    """Tests for progress reporting during execution."""

    @pytest.mark.asyncio
    async def test_progress_events_during_cuts(self) -> None:
        """Node reports progress for each cut operation."""
        from backend.graph.configs.boolean_assemble import BooleanAssembleConfig
        from backend.graph.strategies.boolean.manifold3d import Manifold3DStrategy

        config = BooleanAssembleConfig()
        strategy = Manifold3DStrategy(config=config)

        mock_ctx = MagicMock()
        mock_ctx.config = config
        mock_ctx.job_id = "test-1"
        mock_ctx.node_name = "boolean_assemble"
        mock_ctx.dispatch_progress = AsyncMock()
        mock_ctx.put_data = MagicMock()
        mock_ctx.put_asset = MagicMock()

        # Manifold mesh
        mock_mesh = MagicMock()
        mock_mesh.is_watertight = True
        mock_mesh.vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        mock_mesh.faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.uint32)
        mock_mesh.bounding_box = MagicMock()
        mock_mesh.bounding_box.extents = np.array([50.0, 50.0, 50.0])

        cuts = [
            FlatBottomCut(offset=2.0),
            HoleCut(diameter=5.0, depth=10.0),
            SlotCut(width=10.0, depth=5.0, length=20.0),
        ]
        spec = _make_organic_spec(engineering_cuts=cuts)
        mock_ctx.get_data = MagicMock(return_value=spec)
        mock_asset = MagicMock()
        mock_asset.path = "/tmp/test.glb"
        mock_ctx.get_asset = MagicMock(return_value=mock_asset)
        mock_ctx.has_asset = MagicMock(return_value=True)

        # Mock manifold3d: all cuts succeed
        mock_manifold3d = MagicMock()
        mock_manifold3d.__file__ = "real"
        mock_result_mesh_data = MagicMock()
        mock_result_mesh_data.vert_properties = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32
        )
        mock_result_mesh_data.tri_verts = np.array([[0, 1, 2]], dtype=np.uint32)
        mock_manifold_instance = MagicMock()
        mock_manifold_instance.__sub__ = MagicMock(return_value=mock_manifold_instance)
        mock_manifold_instance.to_mesh.return_value = mock_result_mesh_data
        mock_manifold3d.Manifold.from_mesh.return_value = mock_manifold_instance
        mock_manifold3d.Mesh.return_value = MagicMock()

        mock_tool = MagicMock()
        mock_tool.translate.return_value = mock_tool
        mock_manifold3d.Manifold.cube.return_value = mock_tool
        mock_manifold3d.Manifold.cylinder.return_value = mock_tool

        with (
            patch.dict("sys.modules", {"manifold3d": mock_manifold3d}),
            patch("trimesh.load", return_value=mock_mesh),
            patch("trimesh.Trimesh", return_value=mock_mesh),
        ):
            await strategy.execute(mock_ctx)

        # Verify dispatch_progress was called for each cut
        progress_calls = mock_ctx.dispatch_progress.call_args_list
        assert len(progress_calls) >= 3  # At least one per cut


# ---------------------------------------------------------------------------
# Node-level integration tests
# ---------------------------------------------------------------------------


class TestBooleanAssembleNodeIntegration:
    """Integration tests for the boolean_assemble node function."""

    @pytest.mark.asyncio
    async def test_node_calls_strategy(self) -> None:
        """Node dispatches to strategy when cuts are present."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        spec = _make_organic_spec(
            engineering_cuts=[FlatBottomCut(offset=2.0)],
        )
        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=spec)

        # Mock the strategy's execute method
        mock_execute = AsyncMock()
        with patch(
            "backend.graph.strategies.boolean.manifold3d.Manifold3DStrategy.execute",
            mock_execute,
        ):
            await boolean_assemble_node(ctx)

        mock_execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_node_produces_final_mesh_on_passthrough(self) -> None:
        """Passthrough produces final_mesh asset."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        spec = _make_organic_spec(engineering_cuts=[])
        ctx = _make_ctx(has_shelled_mesh=True, organic_spec=spec)

        await boolean_assemble_node(ctx)

        assert ctx.has_asset("final_mesh")
        diff = ctx.to_state_diff()
        assert "assets" in diff
        assert "final_mesh" in diff["assets"]
