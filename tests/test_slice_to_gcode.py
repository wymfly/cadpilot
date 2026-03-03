"""Tests for slice_to_gcode node — PrusaSlicer + OrcaSlicer strategies + gcode parsing."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# SliceToGcodeConfig
# ---------------------------------------------------------------------------


class TestSliceToGcodeConfig:
    """Config defaults + hardware parameter fields."""

    def test_default_values(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig

        cfg = SliceToGcodeConfig()
        assert cfg.strategy == "prusaslicer"
        assert cfg.prusaslicer_path is None
        assert cfg.orcaslicer_path is None
        assert cfg.layer_height == 0.2
        assert cfg.fill_density == 20
        assert cfg.support_material is False
        assert cfg.nozzle_diameter == 0.4
        assert cfg.filament_type == "PLA"
        assert cfg.timeout == 120
        assert cfg.enabled is True

    def test_custom_hardware_params(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig

        cfg = SliceToGcodeConfig(
            layer_height=0.1,
            fill_density=50,
            support_material=True,
            nozzle_diameter=0.6,
            filament_type="PETG",
        )
        assert cfg.layer_height == 0.1
        assert cfg.fill_density == 50
        assert cfg.support_material is True
        assert cfg.nozzle_diameter == 0.6
        assert cfg.filament_type == "PETG"

    def test_inherits_base_node_config(self):
        from backend.graph.configs.base import BaseNodeConfig
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig

        assert issubclass(SliceToGcodeConfig, BaseNodeConfig)

    def test_configurable_cli_paths(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig

        cfg = SliceToGcodeConfig(
            prusaslicer_path="/usr/local/bin/prusa-slicer",
            orcaslicer_path="/opt/orca-slicer",
        )
        assert cfg.prusaslicer_path == "/usr/local/bin/prusa-slicer"
        assert cfg.orcaslicer_path == "/opt/orca-slicer"

    def test_layer_height_range_validation(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SliceToGcodeConfig(layer_height=0.01)  # below 0.05

        with pytest.raises(ValidationError):
            SliceToGcodeConfig(layer_height=1.0)  # above 0.6

    def test_fill_density_range_validation(self):
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SliceToGcodeConfig(fill_density=-1)

        with pytest.raises(ValidationError):
            SliceToGcodeConfig(fill_density=101)


# ---------------------------------------------------------------------------
# PrusaSlicerStrategy
# ---------------------------------------------------------------------------


class TestPrusaSlicerCheckAvailable:
    """PrusaSlicer availability detection."""

    def test_found_via_shutil_which(self):
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = None
        strategy = PrusaSlicerStrategy(config=config)

        with patch("shutil.which", return_value="/usr/bin/prusa-slicer"):
            assert strategy.check_available() is True

    def test_not_found(self):
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = None
        strategy = PrusaSlicerStrategy(config=config)

        with patch("shutil.which", return_value=None):
            assert strategy.check_available() is False

    def test_config_path_overrides_which(self):
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/custom/prusa-slicer"
        strategy = PrusaSlicerStrategy(config=config)

        # shutil.which not called when config path is set
        assert strategy.check_available() is True


class TestPrusaSlicerExecute:
    """PrusaSlicer CLI execution."""

    def _make_ctx(
        self,
        *,
        mesh_key: str = "final_mesh",
        mesh_path: str = "/tmp/model.stl",
        mesh_format: str = "stl",
    ) -> MagicMock:
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.node_name = "slice_to_gcode"
        ctx.dispatch_progress = AsyncMock()

        asset = MagicMock()
        asset.path = mesh_path
        asset.format = mesh_format

        def get_asset(key):
            if key == mesh_key:
                return asset
            raise KeyError(key)

        ctx.get_asset = MagicMock(side_effect=get_asset)
        ctx.has_asset = MagicMock(side_effect=lambda k: k == mesh_key)
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()

        return ctx

    @pytest.mark.asyncio
    async def test_cli_args_include_all_hardware_params(self):
        """CLI command must include nozzle_diameter, filament_type, etc."""
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/usr/bin/prusa-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = False
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 120

        strategy = PrusaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec, \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"")), \
             patch("backend.graph.strategies.slice.prusaslicer.parse_gcode_metadata", return_value={}), \
             patch("pathlib.Path.exists", return_value=True):

            await strategy.execute(ctx)

            # Verify CLI arguments
            call_args = mock_exec.call_args
            cmd_parts = list(call_args[0])  # positional args are the command parts
            cmd_str = " ".join(str(x) for x in cmd_parts)

            assert "--nozzle-diameter" in cmd_str
            assert "0.4" in cmd_str
            assert "--filament-type" in cmd_str
            assert "PLA" in cmd_str
            assert "--layer-height" in cmd_str
            assert "0.2" in cmd_str
            assert "--fill-density" in cmd_str
            assert "20%" in cmd_str
            assert "--export-gcode" in cmd_str

    @pytest.mark.asyncio
    async def test_support_material_flag(self):
        """--support-material flag added when support_material=True."""
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/usr/bin/prusa-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = True
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 120

        strategy = PrusaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec, \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"")), \
             patch("backend.graph.strategies.slice.prusaslicer.parse_gcode_metadata", return_value={}), \
             patch("pathlib.Path.exists", return_value=True):

            await strategy.execute(ctx)

            cmd_parts = list(mock_exec.call_args[0])
            cmd_str = " ".join(str(x) for x in cmd_parts)
            assert "--support-material" in cmd_str

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        """Timeout triggers exception (auto mode catches for fallback)."""
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/usr/bin/prusa-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = False
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 1

        strategy = PrusaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=asyncio.TimeoutError()):

            with pytest.raises(RuntimeError, match="timed out"):
                await strategy.execute(ctx)

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises(self):
        """Non-zero exit code triggers exception."""
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/usr/bin/prusa-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = False
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 120

        strategy = PrusaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"slice error"))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"slice error")):

            with pytest.raises(RuntimeError, match="exit code 1"):
                await strategy.execute(ctx)

    @pytest.mark.asyncio
    async def test_puts_gcode_bundle_asset(self):
        """Successful slicing produces gcode_bundle asset."""
        from backend.graph.strategies.slice.prusaslicer import PrusaSlicerStrategy

        config = MagicMock()
        config.prusaslicer_path = "/usr/bin/prusa-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = False
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 120

        strategy = PrusaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        metadata = {"layers": 100, "print_time": "1h 30m"}

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc), \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"")), \
             patch("backend.graph.strategies.slice.prusaslicer.parse_gcode_metadata", return_value=metadata), \
             patch("pathlib.Path.exists", return_value=True):

            await strategy.execute(ctx)

            ctx.put_asset.assert_called_once()
            call_args = ctx.put_asset.call_args
            assert call_args[0][0] == "gcode_bundle"
            assert call_args[1]["metadata"] == metadata


# ---------------------------------------------------------------------------
# OrcaSlicerStrategy
# ---------------------------------------------------------------------------


class TestOrcaSlicerCheckAvailable:
    """OrcaSlicer availability detection."""

    def test_found_via_shutil_which(self):
        from backend.graph.strategies.slice.orcaslicer import OrcaSlicerStrategy

        config = MagicMock()
        config.orcaslicer_path = None
        strategy = OrcaSlicerStrategy(config=config)

        with patch("shutil.which", return_value="/usr/bin/orca-slicer"):
            assert strategy.check_available() is True

    def test_not_found(self):
        from backend.graph.strategies.slice.orcaslicer import OrcaSlicerStrategy

        config = MagicMock()
        config.orcaslicer_path = None
        strategy = OrcaSlicerStrategy(config=config)

        with patch("shutil.which", return_value=None):
            assert strategy.check_available() is False

    def test_config_path_overrides(self):
        from backend.graph.strategies.slice.orcaslicer import OrcaSlicerStrategy

        config = MagicMock()
        config.orcaslicer_path = "/opt/orca-slicer"
        strategy = OrcaSlicerStrategy(config=config)

        assert strategy.check_available() is True


class TestOrcaSlicerExecute:
    """OrcaSlicer CLI parameter mapping."""

    def _make_ctx(self, mesh_path: str = "/tmp/model.stl") -> MagicMock:
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.node_name = "slice_to_gcode"
        ctx.dispatch_progress = AsyncMock()

        asset = MagicMock()
        asset.path = mesh_path
        asset.format = "stl"

        ctx.get_asset = MagicMock(return_value=asset)
        ctx.has_asset = MagicMock(return_value=True)
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()

        return ctx

    @pytest.mark.asyncio
    async def test_fill_density_without_percent(self):
        """OrcaSlicer fill_density should NOT have % suffix."""
        from backend.graph.strategies.slice.orcaslicer import OrcaSlicerStrategy

        config = MagicMock()
        config.orcaslicer_path = "/usr/bin/orca-slicer"
        config.layer_height = 0.2
        config.fill_density = 20
        config.support_material = False
        config.nozzle_diameter = 0.4
        config.filament_type = "PLA"
        config.timeout = 120

        strategy = OrcaSlicerStrategy(config=config)
        ctx = self._make_ctx()

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=mock_proc) as mock_exec, \
             patch("asyncio.wait_for", new_callable=AsyncMock, return_value=(b"", b"")), \
             patch("backend.graph.strategies.slice.orcaslicer.parse_gcode_metadata", return_value={}), \
             patch("pathlib.Path.exists", return_value=True):

            await strategy.execute(ctx)

            cmd_parts = list(mock_exec.call_args[0])
            cmd_str = " ".join(str(x) for x in cmd_parts)

            # OrcaSlicer uses fill_density without %
            assert "--fill-density" in cmd_str
            # Check that "20%" is NOT present (instead just "20")
            # Find the fill-density value
            idx = cmd_parts.index("--fill-density")
            assert cmd_parts[idx + 1] == "20"  # no percent sign


# ---------------------------------------------------------------------------
# gcode_parser
# ---------------------------------------------------------------------------


class TestGcodeParser:
    """G-code metadata parsing for various slicer formats."""

    def test_prusaslicer_format(self, tmp_path: Path):
        from backend.core.gcode_parser import parse_gcode_metadata

        gcode = tmp_path / "test.gcode"
        gcode.write_text(
            "; generated by PrusaSlicer 2.7.0\n"
            "G1 X10 Y20 E0.5 F1200\n"
            "G1 X20 Y30 E1.0\n"
            "G1 X30 Y40 E1.5\n"
            ";LAYER_CHANGE\n"
            ";LAYER_CHANGE\n"
            ";LAYER_CHANGE\n"
            "; filament used [mm] = 1234.56\n"
            "; filament used [g] = 3.72\n"
            "; estimated printing time (normal mode) = 1h 30m 15s\n"
            "; total layers count = 150\n"
        )
        meta = parse_gcode_metadata(gcode)
        assert meta["layers"] == 150
        assert meta["filament_used_mm"] == pytest.approx(1234.56)
        assert meta["filament_used_g"] == pytest.approx(3.72)
        assert meta["print_time"] == "1h 30m 15s"
        assert meta["g1_count"] == 3

    def test_orcaslicer_format(self, tmp_path: Path):
        from backend.core.gcode_parser import parse_gcode_metadata

        gcode = tmp_path / "test.gcode"
        gcode.write_text(
            "; generated by OrcaSlicer 2.0.0\n"
            "G1 X10 Y20 E0.5 F1200\n"
            "G1 X20 Y30 E1.0\n"
            "; filament used [mm] = 987.65\n"
            "; filament used [g] = 2.98\n"
            "; total estimated time = 2h 15m 30s\n"
            "; total layers count = 200\n"
        )
        meta = parse_gcode_metadata(gcode)
        assert meta["layers"] == 200
        assert meta["filament_used_mm"] == pytest.approx(987.65)
        assert meta["filament_used_g"] == pytest.approx(2.98)
        assert meta["print_time"] == "2h 15m 30s"
        assert meta["g1_count"] == 2

    def test_parse_failure_returns_empty_dict(self, tmp_path: Path):
        from backend.core.gcode_parser import parse_gcode_metadata

        gcode = tmp_path / "test.gcode"
        gcode.write_text("this is not a valid gcode file\nrandom content\n")
        meta = parse_gcode_metadata(gcode)
        # Should still return something (may have partial or empty data)
        assert isinstance(meta, dict)

    def test_nonexistent_file_returns_empty_dict(self):
        from backend.core.gcode_parser import parse_gcode_metadata

        meta = parse_gcode_metadata(Path("/nonexistent/file.gcode"))
        assert meta == {}

    def test_g1_count(self, tmp_path: Path):
        from backend.core.gcode_parser import parse_gcode_metadata

        gcode = tmp_path / "test.gcode"
        gcode.write_text(
            "G28\n"
            "G1 X10 Y20 E0.5 F1200\n"
            "G1 X20 Y30 E1.0\n"
            "G1 X30 Y40 E1.5\n"
            "G1 X40 Y50 E2.0\n"
            "G1 X50 Y60 E2.5\n"
        )
        meta = parse_gcode_metadata(gcode)
        assert meta["g1_count"] == 5


# ---------------------------------------------------------------------------
# slice_to_gcode node
# ---------------------------------------------------------------------------


class TestSliceToGcodeNode:
    """Node registration + dispatch logic."""

    def test_node_registered_with_strategies(self):
        """slice_to_gcode registered with prusaslicer + orcaslicer strategies."""
        from backend.graph.registry import registry
        import backend.graph.discovery as disc

        disc._discovered = False
        disc.discover_nodes()

        desc = registry.get("slice_to_gcode")
        assert desc is not None
        assert desc.name == "slice_to_gcode"
        assert "prusaslicer" in desc.strategies
        assert "orcaslicer" in desc.strategies
        assert desc.default_strategy == "prusaslicer"
        assert desc.fallback_chain == ["prusaslicer", "orcaslicer"]
        assert "gcode_bundle" in desc.produces
        assert desc.input_types == ["organic"]

    def test_or_dependencies(self):
        """requires has OR dependency list for mesh assets."""
        from backend.graph.registry import registry
        import backend.graph.discovery as disc

        disc._discovered = False
        disc.discover_nodes()

        desc = registry.get("slice_to_gcode")
        # Should have at least one OR-dependency (list)
        has_or = any(isinstance(r, list) for r in desc.requires)
        assert has_or
        # The OR list should contain mesh asset names
        for r in desc.requires:
            if isinstance(r, list):
                assert "final_mesh" in r
                assert "scaled_mesh" in r
                assert "watertight_mesh" in r

    def test_config_model_is_slice_to_gcode_config(self):
        from backend.graph.registry import registry
        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        import backend.graph.discovery as disc

        disc._discovered = False
        disc.discover_nodes()

        desc = registry.get("slice_to_gcode")
        assert desc.config_model is SliceToGcodeConfig


class TestSliceToGcodeBestMesh:
    """Best mesh selection: final_mesh > scaled_mesh > watertight_mesh."""

    def _make_ctx(self, available_assets: dict[str, str]) -> MagicMock:
        """Create mock context with specified available assets."""
        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.node_name = "slice_to_gcode"
        ctx.dispatch_progress = AsyncMock()
        ctx.put_asset = MagicMock()
        ctx.put_data = MagicMock()

        def has_asset(key):
            return key in available_assets

        def get_asset(key):
            if key in available_assets:
                asset = MagicMock()
                asset.path = available_assets[key]
                asset.format = Path(available_assets[key]).suffix.lstrip(".")
                return asset
            raise KeyError(key)

        ctx.has_asset = MagicMock(side_effect=has_asset)
        ctx.get_asset = MagicMock(side_effect=get_asset)

        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        ctx.config = SliceToGcodeConfig()

        return ctx

    @pytest.mark.asyncio
    async def test_prefers_final_mesh(self):
        """final_mesh takes priority over scaled_mesh and watertight_mesh."""
        from backend.graph.nodes.slice_to_gcode import _select_best_mesh

        ctx = self._make_ctx({
            "final_mesh": "/tmp/final.stl",
            "scaled_mesh": "/tmp/scaled.stl",
            "watertight_mesh": "/tmp/watertight.stl",
        })
        key, asset = _select_best_mesh(ctx)
        assert key == "final_mesh"
        assert asset.path == "/tmp/final.stl"

    @pytest.mark.asyncio
    async def test_falls_back_to_scaled_mesh(self):
        from backend.graph.nodes.slice_to_gcode import _select_best_mesh

        ctx = self._make_ctx({
            "scaled_mesh": "/tmp/scaled.stl",
            "watertight_mesh": "/tmp/watertight.stl",
        })
        key, asset = _select_best_mesh(ctx)
        assert key == "scaled_mesh"

    @pytest.mark.asyncio
    async def test_falls_back_to_watertight_mesh(self):
        from backend.graph.nodes.slice_to_gcode import _select_best_mesh

        ctx = self._make_ctx({
            "watertight_mesh": "/tmp/watertight.stl",
        })
        key, asset = _select_best_mesh(ctx)
        assert key == "watertight_mesh"

    @pytest.mark.asyncio
    async def test_no_mesh_returns_none(self):
        from backend.graph.nodes.slice_to_gcode import _select_best_mesh

        ctx = self._make_ctx({})
        result = _select_best_mesh(ctx)
        assert result is None


class TestSliceToGcodeSkip:
    """Node skip conditions."""

    @pytest.mark.asyncio
    async def test_no_mesh_skips(self):
        """No mesh available -> slice_status=skipped_no_mesh."""
        from backend.graph.nodes.slice_to_gcode import slice_to_gcode_node

        ctx = MagicMock()
        ctx.job_id = "test-job"
        ctx.node_name = "slice_to_gcode"
        ctx.dispatch_progress = AsyncMock()
        ctx.put_data = MagicMock()
        ctx.has_asset = MagicMock(return_value=False)

        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        ctx.config = SliceToGcodeConfig()

        await slice_to_gcode_node(ctx)

        ctx.put_data.assert_called_with("slice_status", "skipped_no_mesh")


class TestSliceToGcodeMeshConversion:
    """GLB -> STL auto-conversion before slicing."""

    @pytest.mark.asyncio
    async def test_glb_converted_to_stl(self):
        """GLB mesh triggers convert_mesh to STL."""
        from backend.graph.nodes.slice_to_gcode import _ensure_stl

        ctx = MagicMock()
        ctx.job_id = "test-job"

        asset = MagicMock()
        asset.path = "/tmp/model.glb"
        asset.format = "glb"

        with patch("backend.graph.nodes.slice_to_gcode.convert_mesh", return_value=Path("/tmp/model.stl")) as mock_conv:
            result = _ensure_stl(asset, ctx.job_id)

            mock_conv.assert_called_once()
            assert str(result).endswith(".stl")

    @pytest.mark.asyncio
    async def test_stl_passthrough(self):
        """STL mesh is used directly without conversion."""
        from backend.graph.nodes.slice_to_gcode import _ensure_stl

        ctx = MagicMock()
        ctx.job_id = "test-job"

        asset = MagicMock()
        asset.path = "/tmp/model.stl"
        asset.format = "stl"

        result = _ensure_stl(asset, ctx.job_id)
        assert str(result) == "/tmp/model.stl"


class TestSliceToGcodeAllStrategiesFail:
    """All strategies fail -> job marked failed."""

    @pytest.mark.asyncio
    async def test_all_fail_raises(self):
        """Auto mode with all strategies failing raises RuntimeError."""
        from backend.graph.descriptor import NodeDescriptor, NodeStrategy
        from backend.graph.context import NodeContext, AssetRegistry

        class FailPrusa(NodeStrategy):
            def check_available(self):
                return False

            async def execute(self, ctx):
                raise RuntimeError("prusa unavailable")

        class FailOrca(NodeStrategy):
            def check_available(self):
                return False

            async def execute(self, ctx):
                raise RuntimeError("orca unavailable")

        async def fail_node(ctx):
            await ctx.execute_with_fallback()

        desc = NodeDescriptor(
            name="test_slice_fail",
            display_name="Test Slice Fail",
            fn=fail_node,
            strategies={"prusaslicer": FailPrusa, "orcaslicer": FailOrca},
            default_strategy="prusaslicer",
            fallback_chain=["prusaslicer", "orcaslicer"],
        )

        assets = AssetRegistry()
        assets.put("final_mesh", "/tmp/model.stl", "stl", "test")

        from backend.graph.configs.slice_to_gcode import SliceToGcodeConfig
        config = SliceToGcodeConfig(strategy="auto")

        ctx = NodeContext(
            job_id="test-job",
            input_type="organic",
            assets=assets,
            data={},
            config=config,
            descriptor=desc,
            node_name="test_slice_fail",
        )

        with pytest.raises(RuntimeError, match="No strategy succeeded"):
            await fail_node(ctx)
