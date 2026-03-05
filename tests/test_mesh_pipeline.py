"""Tests for organic mesh pipeline nodes (mesh_healer, mesh_scale, boolean_assemble).

Validates that pipeline nodes are properly registered in NodeRegistry
and that their implementations work with NodeContext.

Note: boolean_cuts and export_formats stubs have been replaced by
boolean_assemble (Phase 2 Task 3). export_formats will be re-added later.
"""

from __future__ import annotations

import pytest

from backend.graph.context import AssetRegistry, NodeContext
from backend.graph.configs.base import BaseNodeConfig
from backend.graph.registry import registry


def _reset_registry() -> None:
    """Force re-discovery so newly added modules are registered."""
    import backend.graph.discovery as disc

    disc._discovered = False
    disc.discover_nodes()


@pytest.fixture(autouse=True, scope="module")
def _ensure_discovery() -> None:
    _reset_registry()


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestMeshNodeRegistration:
    """Verify organic mesh nodes are registered with correct metadata."""

    def test_mesh_healer_registered(self) -> None:
        desc = registry.get("mesh_healer")
        assert desc.display_name == "网格修复"
        assert desc.requires == ["raw_mesh"]
        assert desc.produces == ["watertight_mesh"]
        assert desc.input_types == ["organic"]

    def test_mesh_scale_registered(self) -> None:
        desc = registry.get("mesh_scale")
        assert desc.display_name == "网格缩放"
        assert desc.requires == ["watertight_mesh"]
        assert desc.produces == ["scaled_mesh"]
        assert desc.input_types == ["organic"]

    def test_boolean_assemble_registered(self) -> None:
        desc = registry.get("boolean_assemble")
        assert desc.display_name == "布尔装配"
        assert desc.requires == ["shelled_mesh"]
        assert desc.produces == ["final_mesh"]
        assert desc.input_types == ["organic"]

    def test_pipeline_chain_produces_matches_requires(self) -> None:
        """Verify the dependency chain: repair -> scale -> shell -> boolean_assemble."""
        repair = registry.get("mesh_healer")
        scale = registry.get("mesh_scale")
        shell = registry.get("shell_node")
        assemble = registry.get("boolean_assemble")

        # repair produces what scale requires
        assert "watertight_mesh" in repair.produces
        assert "watertight_mesh" in scale.requires

        # scale produces what shell_node requires
        assert "scaled_mesh" in scale.produces
        assert "scaled_mesh" in shell.requires

        # shell_node produces what boolean_assemble requires
        assert "shelled_mesh" in shell.produces
        assert "shelled_mesh" in assemble.requires

        # boolean_assemble produces final_mesh
        assert "final_mesh" in assemble.produces


# ---------------------------------------------------------------------------
# Placeholder execution tests
# ---------------------------------------------------------------------------


def _make_ctx(node_name: str, data: dict | None = None, assets: dict | None = None) -> NodeContext:
    """Build a minimal NodeContext for testing."""
    desc = registry.get(node_name)
    asset_reg = AssetRegistry()
    if assets:
        for key, path in assets.items():
            asset_reg.put(key, path, "mesh", "test")
    config = desc.config_model() if desc.config_model else BaseNodeConfig()
    return NodeContext(
        job_id="test-mesh-1",
        input_type="organic",
        assets=asset_reg,
        data=data or {},
        config=config,
        descriptor=desc,
        node_name=node_name,
    )


class TestMeshHealerNode:
    @pytest.mark.asyncio
    async def test_strategy_execute_called_with_path(self) -> None:
        """Strategy.execute is called when raw_mesh_path is provided."""
        from unittest.mock import AsyncMock, patch

        from backend.graph.nodes.mesh_healer import mesh_healer_node

        ctx = _make_ctx("mesh_healer", data={"raw_mesh_path": "/tmp/raw.glb"})
        mock_exec = AsyncMock()
        with patch.object(
            type(ctx.get_strategy()), "execute", mock_exec,
        ):
            await mesh_healer_node(ctx)
        mock_exec.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_when_no_raw_mesh(self) -> None:
        """Node skips gracefully when no raw mesh is available (upstream failed)."""
        from backend.graph.nodes.mesh_healer import mesh_healer_node

        ctx = _make_ctx("mesh_healer", data={})
        await mesh_healer_node(ctx)
        assert ctx.get_data("mesh_healer_status") == "skipped_no_input"


class TestMeshScaleNode:
    @pytest.mark.asyncio
    async def test_passthrough_without_organic_spec(self) -> None:
        """No organic_spec in data -> passthrough (watertight_mesh = scaled_mesh)."""
        import tempfile
        import trimesh

        from backend.graph.nodes.mesh_scale import mesh_scale_node

        # Create a real mesh file for the node to load
        mesh = trimesh.primitives.Box().to_mesh()
        tmp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        mesh.export(tmp.name)
        tmp.close()

        ctx = _make_ctx(
            "mesh_scale",
            assets={"watertight_mesh": tmp.name},
        )
        await mesh_scale_node(ctx)
        assert ctx.has_asset("scaled_mesh")
        assert ctx.get_data("mesh_scale_status") == "passthrough"

    @pytest.mark.asyncio
    async def test_skips_without_asset(self) -> None:
        from backend.graph.nodes.mesh_scale import mesh_scale_node

        ctx = _make_ctx("mesh_scale")
        await mesh_scale_node(ctx)
        assert not ctx.has_asset("scaled_mesh")
        assert ctx.get_data("mesh_scale_status") == "skipped_no_input"


class TestBooleanAssembleNode:
    @pytest.mark.asyncio
    async def test_passthrough_without_cuts(self) -> None:
        """No engineering_cuts -> passthrough shelled_mesh as final_mesh."""
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = _make_ctx(
            "boolean_assemble",
            assets={"shelled_mesh": "/tmp/shelled.glb"},
        )
        await boolean_assemble_node(ctx)
        assert ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "passthrough_no_cuts"

    @pytest.mark.asyncio
    async def test_skips_without_asset(self) -> None:
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        ctx = _make_ctx("boolean_assemble")
        await boolean_assemble_node(ctx)
        assert not ctx.has_asset("final_mesh")
        assert ctx.get_data("boolean_assemble_status") == "skipped_no_input"
