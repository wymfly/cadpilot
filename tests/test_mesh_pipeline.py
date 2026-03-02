"""Tests for organic mesh pipeline nodes (mesh_repair, mesh_scale, boolean_cuts, export_formats).

Validates that all 4 new nodes are properly registered in NodeRegistry
and that their placeholder implementations work with NodeContext.
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
    """Verify all 4 organic mesh nodes are registered with correct metadata."""

    def test_mesh_repair_registered(self) -> None:
        desc = registry.get("mesh_repair")
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

    def test_boolean_cuts_registered(self) -> None:
        desc = registry.get("boolean_cuts")
        assert desc.display_name == "布尔运算"
        assert desc.requires == ["scaled_mesh"]
        assert desc.produces == ["final_mesh"]
        assert desc.input_types == ["organic"]

    def test_export_formats_registered(self) -> None:
        desc = registry.get("export_formats")
        assert desc.display_name == "导出格式"
        assert desc.requires == [["final_mesh", "scaled_mesh", "watertight_mesh"]]
        assert desc.produces == ["export_bundle"]
        assert desc.input_types == ["organic"]

    def test_pipeline_chain_produces_matches_requires(self) -> None:
        """Verify the dependency chain: repair → scale → cuts → export."""
        repair = registry.get("mesh_repair")
        scale = registry.get("mesh_scale")
        cuts = registry.get("boolean_cuts")
        export = registry.get("export_formats")

        # repair produces what scale requires
        assert "watertight_mesh" in repair.produces
        assert "watertight_mesh" in scale.requires

        # scale produces what cuts requires
        assert "scaled_mesh" in scale.produces
        assert "scaled_mesh" in cuts.requires

        # cuts produces what export can consume (OR dependency)
        assert "final_mesh" in cuts.produces
        or_deps = export.requires[0]
        assert isinstance(or_deps, list)
        assert "final_mesh" in or_deps


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
    return NodeContext(
        job_id="test-mesh-1",
        input_type="organic",
        assets=asset_reg,
        data=data or {},
        config=BaseNodeConfig(),
        descriptor=desc,
        node_name=node_name,
    )


class TestMeshRepairNode:
    @pytest.mark.asyncio
    async def test_placeholder_with_path(self) -> None:
        from backend.graph.nodes.mesh_repair import mesh_repair_node

        ctx = _make_ctx("mesh_repair", data={"raw_mesh_path": "/tmp/raw.glb"})
        await mesh_repair_node(ctx)
        assert ctx.has_asset("watertight_mesh")

    @pytest.mark.asyncio
    async def test_skips_without_path(self) -> None:
        from backend.graph.nodes.mesh_repair import mesh_repair_node

        ctx = _make_ctx("mesh_repair", data={})
        await mesh_repair_node(ctx)
        assert not ctx.has_asset("watertight_mesh")


class TestMeshScaleNode:
    @pytest.mark.asyncio
    async def test_placeholder_with_asset(self) -> None:
        from backend.graph.nodes.mesh_scale import mesh_scale_node

        ctx = _make_ctx(
            "mesh_scale",
            assets={"watertight_mesh": "/tmp/repaired.glb"},
        )
        await mesh_scale_node(ctx)
        assert ctx.has_asset("scaled_mesh")

    @pytest.mark.asyncio
    async def test_skips_without_asset(self) -> None:
        from backend.graph.nodes.mesh_scale import mesh_scale_node

        ctx = _make_ctx("mesh_scale")
        await mesh_scale_node(ctx)
        assert not ctx.has_asset("scaled_mesh")


class TestBooleanCutsNode:
    @pytest.mark.asyncio
    async def test_placeholder_with_asset(self) -> None:
        from backend.graph.nodes.boolean_cuts import boolean_cuts_node

        ctx = _make_ctx(
            "boolean_cuts",
            assets={"scaled_mesh": "/tmp/scaled.glb"},
        )
        await boolean_cuts_node(ctx)
        assert ctx.has_asset("final_mesh")

    @pytest.mark.asyncio
    async def test_skips_without_asset(self) -> None:
        from backend.graph.nodes.boolean_cuts import boolean_cuts_node

        ctx = _make_ctx("boolean_cuts")
        await boolean_cuts_node(ctx)
        assert not ctx.has_asset("final_mesh")


class TestExportFormatsNode:
    @pytest.mark.asyncio
    async def test_placeholder_selects_best_mesh(self) -> None:
        from backend.graph.nodes.export_formats import export_formats_node

        # Provide final_mesh — should pick it
        ctx = _make_ctx(
            "export_formats",
            assets={"final_mesh": "/tmp/final.glb", "scaled_mesh": "/tmp/scaled.glb"},
        )
        await export_formats_node(ctx)
        assert ctx.has_asset("export_bundle")
        assert ctx.get_data("export_source_mesh") == "final_mesh"

    @pytest.mark.asyncio
    async def test_falls_back_to_watertight(self) -> None:
        from backend.graph.nodes.export_formats import export_formats_node

        ctx = _make_ctx(
            "export_formats",
            assets={"watertight_mesh": "/tmp/watertight.glb"},
        )
        await export_formats_node(ctx)
        assert ctx.has_asset("export_bundle")
        assert ctx.get_data("export_source_mesh") == "watertight_mesh"

    @pytest.mark.asyncio
    async def test_skips_without_any_mesh(self) -> None:
        from backend.graph.nodes.export_formats import export_formats_node

        ctx = _make_ctx("export_formats")
        await export_formats_node(ctx)
        assert not ctx.has_asset("export_bundle")
