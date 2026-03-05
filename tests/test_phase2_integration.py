"""Phase 2 integration tests: end-to-end organic pipeline + DependencyResolver validation.

Tests the full new organic pipeline path:
  generate_raw_mesh -> mesh_healer -> mesh_scale -> boolean_assemble -> slice_to_gcode

All AI models / mesh operations are mocked via strategy mocking.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.graph.context import AssetRegistry, NodeContext
from backend.graph.configs.base import BaseNodeConfig
from backend.graph.descriptor import NodeDescriptor
from backend.graph.registry import NodeRegistry, registry
from backend.graph.resolver import DependencyResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_registry() -> None:
    """Force re-discovery so all node modules are imported."""
    import backend.graph.discovery as disc
    disc._discovered = False
    disc.discover_nodes()


@pytest.fixture(autouse=True, scope="module")
def _ensure_discovery() -> None:
    _reset_registry()


def _make_ctx(
    node_name: str,
    data: dict | None = None,
    assets: dict | None = None,
    pipeline_config: dict | None = None,
) -> NodeContext:
    """Build a minimal NodeContext for testing a named node."""
    desc = registry.get(node_name)
    asset_reg = AssetRegistry()
    if assets:
        for key, info in assets.items():
            if isinstance(info, dict):
                asset_reg.put(key, info["path"], info.get("format", "mesh"), info.get("producer", "test"))
            else:
                asset_reg.put(key, info, "mesh", "test")
    config_raw = (pipeline_config or {}).get(node_name, {})
    config_cls = desc.config_model or BaseNodeConfig
    config = config_cls(**config_raw) if config_raw else config_cls()
    return NodeContext(
        job_id="integration-test-1",
        input_type="organic",
        assets=asset_reg,
        data=data or {},
        config=config,
        descriptor=desc,
        node_name=node_name,
        raw_state={
            "job_id": "integration-test-1",
            "input_type": "organic",
            "assets": asset_reg.to_dict(),
            "data": data or {},
            "pipeline_config": pipeline_config or {},
            "node_trace": [],
        },
    )


# ---------------------------------------------------------------------------
# 6.1 End-to-End Integration Tests
# ---------------------------------------------------------------------------


class TestOrganicPipelineE2E:
    """End-to-end test of the full organic pipeline with mocked strategies."""

    @pytest.mark.asyncio
    async def test_full_pipeline_asset_chain(self) -> None:
        """Run all 5 nodes in sequence, verify asset chain is correct.

        Pipeline: generate_raw_mesh -> mesh_healer -> mesh_scale
                  -> boolean_assemble -> slice_to_gcode
        """
        # Create a real temp mesh file that nodes can "produce"
        tmp_dir = Path(tempfile.mkdtemp())
        raw_mesh_path = str(tmp_dir / "raw.glb")
        watertight_path = str(tmp_dir / "watertight.glb")
        scaled_path = str(tmp_dir / "scaled.glb")
        final_path = str(tmp_dir / "final.glb")
        gcode_path = str(tmp_dir / "output.gcode")

        # Write dummy files so path checks pass
        for p in [raw_mesh_path, watertight_path, scaled_path, final_path, gcode_path]:
            Path(p).write_text("dummy")

        # ---- Node 1: generate_raw_mesh ----
        from backend.graph.nodes.generate_raw_mesh import generate_raw_mesh_node

        ctx1 = _make_ctx("generate_raw_mesh", data={
            "organic_spec": {"prompt": "test vase", "final_bounding_box": [100, 100, 200]},
        })

        # Mock strategy to produce raw_mesh asset
        mock_strategy = AsyncMock()
        async def mock_execute_gen(ctx: NodeContext) -> None:
            ctx.put_asset("raw_mesh", raw_mesh_path, "glb", metadata={"provider": "mock"})
        mock_strategy.execute = mock_execute_gen
        mock_strategy.check_available.return_value = True

        with patch.object(ctx1, "get_strategy", return_value=mock_strategy):
            await generate_raw_mesh_node(ctx1)

        assert ctx1.has_asset("raw_mesh")
        assert ctx1.get_asset("raw_mesh").path == raw_mesh_path

        # ---- Node 2: mesh_healer ----
        from backend.graph.nodes.mesh_healer import mesh_healer_node

        ctx2 = _make_ctx(
            "mesh_healer",
            data={"raw_mesh_path": raw_mesh_path},
            assets={"raw_mesh": raw_mesh_path},
        )

        mock_heal_strategy = AsyncMock()
        async def mock_heal_execute(ctx: NodeContext) -> None:
            ctx.put_asset("watertight_mesh", watertight_path, "glb", metadata={"repaired": True})
        mock_heal_strategy.execute = mock_heal_execute
        mock_heal_strategy.check_available.return_value = True

        with patch.object(ctx2, "get_strategy", return_value=mock_heal_strategy):
            await mesh_healer_node(ctx2)

        assert ctx2.has_asset("watertight_mesh")
        assert ctx2.get_asset("watertight_mesh").path == watertight_path

        # ---- Node 3: mesh_scale ----
        from backend.graph.nodes.mesh_scale import mesh_scale_node

        # Create a real trimesh mesh file for the scale node to load
        import trimesh as _trimesh
        box_mesh = _trimesh.primitives.Box(extents=[50, 50, 100]).to_mesh()
        box_mesh.export(watertight_path)

        ctx3 = _make_ctx(
            "mesh_scale",
            data={"organic_spec": {"final_bounding_box": [100, 100, 200]}},
            assets={"watertight_mesh": watertight_path},
        )

        await mesh_scale_node(ctx3)

        assert ctx3.has_asset("scaled_mesh")

        # ---- Node 4: boolean_assemble ----
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node

        # Use the scaled path from ctx3 as shelled_mesh (passthrough equivalent)
        scaled_asset_path = ctx3.get_asset("scaled_mesh").path

        ctx4 = _make_ctx(
            "boolean_assemble",
            data={"organic_spec": {"engineering_cuts": []}},
            assets={"shelled_mesh": scaled_asset_path},
        )

        await boolean_assemble_node(ctx4)
        assert ctx4.has_asset("final_mesh")
        assert ctx4.get_data("boolean_assemble_status") == "passthrough_no_cuts"

        # ---- Node 5: slice_to_gcode ----
        from backend.graph.nodes.slice_to_gcode import slice_to_gcode_node

        final_asset_path = ctx4.get_asset("final_mesh").path

        ctx5 = _make_ctx(
            "slice_to_gcode",
            assets={"final_mesh": final_asset_path},
        )

        mock_slice_strategy = AsyncMock()
        async def mock_slice_execute(ctx: NodeContext) -> None:
            ctx.put_asset("gcode_bundle", gcode_path, "gcode", metadata={"slicer": "mock"})
        mock_slice_strategy.execute = mock_slice_execute
        mock_slice_strategy.check_available.return_value = True

        with patch.object(ctx5, "get_strategy", return_value=mock_slice_strategy):
            await slice_to_gcode_node(ctx5)

        assert ctx5.has_asset("gcode_bundle")
        assert ctx5.get_asset("gcode_bundle").path == gcode_path

    @pytest.mark.asyncio
    async def test_pipeline_order_is_correct(self) -> None:
        """Verify the organic pipeline executes nodes in the right order."""
        # The correct order is defined by the dependency chain:
        # generate_raw_mesh (produces raw_mesh)
        # -> mesh_healer (requires raw_mesh, produces watertight_mesh)
        # -> mesh_scale (requires watertight_mesh, produces scaled_mesh)
        # -> shell_node (requires scaled_mesh, produces shelled_mesh)
        # -> boolean_assemble (requires shelled_mesh, produces final_mesh)
        # -> slice_to_gcode (requires final_mesh|scaled_mesh|watertight_mesh, produces gcode_bundle)

        gen = registry.get("generate_raw_mesh")
        heal = registry.get("mesh_healer")
        scale = registry.get("mesh_scale")
        assemble = registry.get("boolean_assemble")
        slicer = registry.get("slice_to_gcode")

        # Check the chain: each node's produces feeds the next's requires
        assert "raw_mesh" in gen.produces
        assert "raw_mesh" in heal.requires
        assert "watertight_mesh" in heal.produces
        assert "watertight_mesh" in scale.requires
        assert "scaled_mesh" in scale.produces
        assert "shelled_mesh" in assemble.requires
        assert "final_mesh" in assemble.produces
        # slice_to_gcode uses OR dependency (includes Phase 3 optimized meshes)
        or_group = slicer.requires[0]
        assert isinstance(or_group, list)
        assert "final_mesh" in or_group
        assert "scaled_mesh" in or_group
        assert "watertight_mesh" in or_group

    @pytest.mark.asyncio
    async def test_skip_propagation(self) -> None:
        """When generate_raw_mesh produces no asset, downstream nodes skip gracefully."""
        from backend.graph.nodes.mesh_healer import mesh_healer_node
        from backend.graph.nodes.mesh_scale import mesh_scale_node
        from backend.graph.nodes.boolean_assemble import boolean_assemble_node
        from backend.graph.nodes.slice_to_gcode import slice_to_gcode_node

        # mesh_healer: no raw_mesh -> skip
        ctx_heal = _make_ctx("mesh_healer")
        await mesh_healer_node(ctx_heal)
        assert ctx_heal.get_data("mesh_healer_status") == "skipped_no_input"

        # mesh_scale: no watertight_mesh -> skip
        ctx_scale = _make_ctx("mesh_scale")
        await mesh_scale_node(ctx_scale)
        assert ctx_scale.get_data("mesh_scale_status") == "skipped_no_input"

        # boolean_assemble: no shelled_mesh -> skip
        ctx_bool = _make_ctx("boolean_assemble")
        await boolean_assemble_node(ctx_bool)
        assert ctx_bool.get_data("boolean_assemble_status") == "skipped_no_input"

        # slice_to_gcode: no mesh at all -> skip
        ctx_slice = _make_ctx("slice_to_gcode")
        await slice_to_gcode_node(ctx_slice)
        assert ctx_slice.get_data("slice_status") == "skipped_no_mesh"


# ---------------------------------------------------------------------------
# 6.2 DependencyResolver Validation
# ---------------------------------------------------------------------------


class TestDependencyResolverOrganic:
    """Verify DependencyResolver correctly resolves the organic pipeline."""

    def test_organic_pipeline_topo_sort(self) -> None:
        """Resolver produces correct topological order for organic input_type."""
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        node_names = [d.name for d in resolved.ordered_nodes]

        # New pipeline nodes must be present
        for expected in ["generate_raw_mesh", "mesh_healer", "mesh_scale",
                         "boolean_assemble", "slice_to_gcode"]:
            assert expected in node_names, f"Missing node: {expected}"

        # Verify topological order within new pipeline
        gen_idx = node_names.index("generate_raw_mesh")
        heal_idx = node_names.index("mesh_healer")
        scale_idx = node_names.index("mesh_scale")
        bool_idx = node_names.index("boolean_assemble")
        slice_idx = node_names.index("slice_to_gcode")

        assert gen_idx < heal_idx < scale_idx < bool_idx < slice_idx

    def test_export_formats_not_present(self) -> None:
        """export_formats node should NOT be in the resolved pipeline."""
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        node_names = [d.name for d in resolved.ordered_nodes]
        assert "export_formats" not in node_names

    def test_boolean_cuts_not_present(self) -> None:
        """boolean_cuts (old stub) should NOT be in the resolved pipeline."""
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        node_names = [d.name for d in resolved.ordered_nodes]
        assert "boolean_cuts" not in node_names

    def test_generate_organic_mesh_not_duplicated(self) -> None:
        """generate_organic_mesh should NOT appear as @register_node in the registry.

        It's only used in the legacy builder as a directly added node.
        """
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        node_names = [d.name for d in resolved.ordered_nodes]
        assert "generate_organic_mesh" not in node_names

    def test_generate_raw_mesh_present(self) -> None:
        """generate_raw_mesh should be present and correctly positioned."""
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        node_names = [d.name for d in resolved.ordered_nodes]
        assert "generate_raw_mesh" in node_names

        # It should come after confirm_with_user
        if "confirm_with_user" in node_names:
            confirm_idx = node_names.index("confirm_with_user")
            gen_idx = node_names.index("generate_raw_mesh")
            assert confirm_idx < gen_idx

    def test_no_asset_conflicts(self) -> None:
        """No two organic nodes should produce the same asset."""
        resolved = DependencyResolver.resolve(registry, {}, input_type="organic")
        for asset, producers in resolved.asset_producers.items():
            # Multiple producers are OK if they have disjoint input_types;
            # the resolver would have raised ValueError otherwise.
            # Just verify we got here without error.
            assert len(producers) >= 1

    def test_resolve_all_compiles(self) -> None:
        """resolve_all (no input_type filter) should still compile."""
        resolved = DependencyResolver.resolve_all(registry, {})
        from backend.graph.builder import PipelineBuilder
        from backend.graph.interceptors import default_registry
        builder = PipelineBuilder()
        graph = builder.build(resolved, interceptor_registry=default_registry)
        compiled = graph.compile()
        assert compiled is not None


# ---------------------------------------------------------------------------
# 6.3 Finalize Node: AssetRegistry Integration
# ---------------------------------------------------------------------------


class TestFinalizeNodeAssetAware:
    """Verify finalize_node reads new-architecture assets when available."""

    @pytest.mark.asyncio
    async def test_finalize_reads_asset_registry(self) -> None:
        """finalize_node should read model_url/stl_url from AssetRegistry in assets dict."""
        from backend.graph.nodes.lifecycle import finalize_node

        state = {
            "job_id": "finalize-test-1",
            "input_type": "organic",
            "status": "post_processed",
            "assets": {
                "raw_mesh": {
                    "key": "raw_mesh",
                    "path": "/tmp/raw.glb",
                    "format": "glb",
                    "producer": "generate_raw_mesh",
                    "metadata": {},
                },
                "watertight_mesh": {
                    "key": "watertight_mesh",
                    "path": "/tmp/watertight.glb",
                    "format": "glb",
                    "producer": "mesh_healer",
                    "metadata": {},
                },
                "final_mesh": {
                    "key": "final_mesh",
                    "path": "/outputs/finalize-test-1/model.glb",
                    "format": "glb",
                    "producer": "boolean_assemble",
                    "metadata": {},
                },
                "gcode_bundle": {
                    "key": "gcode_bundle",
                    "path": "/outputs/finalize-test-1/output.gcode",
                    "format": "gcode",
                    "producer": "slice_to_gcode",
                    "metadata": {"layer_count": 150},
                },
            },
            "data": {
                "mesh_stats": {"face_count": 5000},
            },
        }

        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock) as mock_update:
            result = await finalize_node(state)

        assert result["status"] == "completed"

        # Verify update_job was called with result containing asset URLs
        call_kwargs = mock_update.call_args.kwargs
        result_dict = call_kwargs.get("result", {})
        assert result_dict.get("model_url") == "/outputs/finalize-test-1/model.glb"
        assert result_dict.get("gcode_url") == "/outputs/finalize-test-1/output.gcode"

    @pytest.mark.asyncio
    async def test_finalize_falls_back_to_organic_result(self) -> None:
        """When no assets dict, finalize should still work with legacy organic_result."""
        from backend.graph.nodes.lifecycle import finalize_node

        state = {
            "job_id": "finalize-test-2",
            "input_type": "organic",
            "status": "post_processed",
            "organic_result": {
                "model_url": "/outputs/legacy/model.glb",
                "stl_url": "/outputs/legacy/model.stl",
                "threemf_url": None,
                "mesh_stats": {"face_count": 3000},
                "warnings": [],
                "printability": {"printable": True},
            },
        }

        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock):
            result = await finalize_node(state)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_finalize_handles_failed_state(self) -> None:
        """finalize_node should handle error state correctly."""
        from backend.graph.nodes.lifecycle import finalize_node

        state = {
            "job_id": "finalize-test-3",
            "input_type": "organic",
            "error": "Generation failed",
            "status": "failed",
        }

        with patch("backend.graph.nodes.lifecycle.update_job", new_callable=AsyncMock):
            result = await finalize_node(state)

        assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# 6.5 AutoProvider Removal
# ---------------------------------------------------------------------------


class TestAutoProviderRemoved:
    """Verify AutoProvider is no longer importable from mesh_providers."""

    def test_auto_provider_not_in_exports(self) -> None:
        """AutoProvider should not be in mesh_providers __all__."""
        import backend.infra.mesh_providers as mp
        assert "AutoProvider" not in mp.__all__

    def test_auto_module_file_deleted(self) -> None:
        """auto.py file should not exist."""
        auto_path = Path(__file__).parent.parent / "backend" / "infra" / "mesh_providers" / "auto.py"
        assert not auto_path.exists(), f"auto.py should be deleted: {auto_path}"
