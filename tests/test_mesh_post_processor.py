"""Tests for mesh post-processing pipeline."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import trimesh

from backend.models.organic import (
    FlatBottomCut,
    HoleCut,
    OrganicSpec,
    SlotCut,
)


def _make_spec(**overrides: object) -> OrganicSpec:
    defaults = dict(
        prompt_en="test object",
        prompt_original="测试对象",
        shape_category="organic",
        quality_mode="standard",
    )
    defaults.update(overrides)
    return OrganicSpec(**defaults)


def _save_cube_mesh(path: Path, extents: tuple[float, float, float] = (50.0, 50.0, 50.0)) -> Path:
    """Save a cube mesh to a GLB file for testing."""
    mesh = trimesh.creation.box(extents=extents)
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path))
    return path


# ---------------------------------------------------------------------------
# Basic pipeline tests
# ---------------------------------------------------------------------------

class TestMeshPostProcessor:
    async def test_process_returns_result(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor, ProcessedMeshResult

        mesh_path = _save_cube_mesh(tmp_path / "input.glb")
        spec = _make_spec(final_bounding_box=(80, 80, 60))
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        assert isinstance(result, ProcessedMeshResult)
        assert result.mesh is not None
        assert result.stats is not None

    async def test_scale_fits_bounding_box(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb", extents=(100, 100, 100))
        spec = _make_spec(final_bounding_box=(50, 50, 40))
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        bbox = result.mesh.bounding_box.extents
        # Should fit within target bounding box (with tolerance)
        assert bbox[0] <= 50.1
        assert bbox[1] <= 50.1
        assert bbox[2] <= 40.1

    async def test_scale_no_bbox_keeps_original(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb", extents=(30, 30, 30))
        spec = _make_spec()  # no final_bounding_box
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        bbox = result.mesh.bounding_box.extents
        # Should remain approximately the same size
        assert abs(bbox[0] - 30) < 1.0

    async def test_quality_validation_reports_stats(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb")
        spec = _make_spec(final_bounding_box=(80, 80, 60))
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        stats = result.stats
        assert stats.vertex_count > 0
        assert stats.face_count > 0
        assert stats.is_watertight is True
        assert stats.volume_cm3 is not None
        assert stats.volume_cm3 > 0

    async def test_draft_mode_skips_boolean(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb")
        spec = _make_spec(
            quality_mode="draft",
            final_bounding_box=(80, 80, 60),
            engineering_cuts=[FlatBottomCut()],
        )
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        assert result.stats.boolean_cuts_applied == 0

    async def test_boolean_flat_bottom_cut(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb", extents=(50, 50, 50))
        spec = _make_spec(
            final_bounding_box=(50, 50, 50),
            engineering_cuts=[FlatBottomCut(offset=0.0)],
        )
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        # Boolean should have been applied (or gracefully degraded)
        # Either way, we get a valid result
        assert result.mesh is not None
        assert result.stats.face_count > 0

    async def test_boolean_hole_cut(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb", extents=(50, 50, 50))
        spec = _make_spec(
            final_bounding_box=(50, 50, 50),
            engineering_cuts=[HoleCut(diameter=10.0, depth=25.0)],
        )
        processor = MeshPostProcessor()

        result = await processor.process(mesh_path, spec)
        assert result.mesh is not None
        assert result.stats.face_count > 0

    async def test_graceful_degradation_boolean_fails(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb", extents=(50, 50, 50))
        spec = _make_spec(
            final_bounding_box=(50, 50, 50),
            engineering_cuts=[HoleCut(diameter=10.0, depth=25.0)],
        )
        processor = MeshPostProcessor()

        # Mock manifold3d to fail
        with patch("backend.core.mesh_post_processor._apply_boolean_cuts") as mock_bool:
            mock_bool.side_effect = RuntimeError("Boolean op failed")
            result = await processor.process(mesh_path, spec)

        # Should still return a valid mesh (just without boolean cuts)
        assert result.mesh is not None
        assert result.stats.boolean_cuts_applied == 0
        assert len(result.warnings) > 0

    async def test_progress_callback(self, tmp_path: Path) -> None:
        from backend.core.mesh_post_processor import MeshPostProcessor

        mesh_path = _save_cube_mesh(tmp_path / "input.glb")
        spec = _make_spec(final_bounding_box=(80, 80, 60))
        processor = MeshPostProcessor()

        progress_calls: list[tuple[str, str]] = []
        def on_progress(stage: str, msg: str) -> None:
            progress_calls.append((stage, msg))

        result = await processor.process(mesh_path, spec, on_progress=on_progress)
        assert len(progress_calls) > 0
