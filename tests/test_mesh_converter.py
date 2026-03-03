"""Tests for mesh format conversion utility + asset export API endpoint.

convert_mesh() supports OBJ/GLB/STL/3MF inter-conversion via trimesh.
Same-format passthrough uses shutil.copy2 (no trimesh involvement).
Unsupported format raises ValueError with supported format list.

Export API: GET /api/jobs/{job_id}/assets/{asset_key}?format=...
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =========================================================================
# convert_mesh() unit tests
# =========================================================================


class TestConvertMesh:
    """Unit tests for backend.core.mesh_converter.convert_mesh."""

    def test_same_format_uses_copy(self, tmp_path: Path) -> None:
        """Same input/output format → shutil.copy2, no trimesh."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "mesh.stl"
        src.write_bytes(b"solid dummy\nendsolid")
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        with patch("backend.core.mesh_converter.shutil") as mock_shutil:
            mock_shutil.copy2 = shutil.copy2  # use real copy2
            result = convert_mesh(src, "stl", out_dir)

        assert result == out_dir / "mesh.stl"
        assert result.exists()

    def test_same_format_preserves_content(self, tmp_path: Path) -> None:
        """Same-format copy preserves original file content exactly."""
        from backend.core.mesh_converter import convert_mesh

        content = b"binary stl data here"
        src = tmp_path / "model.obj"
        src.write_bytes(content)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = convert_mesh(src, "obj", out_dir)
        assert result.read_bytes() == content

    def test_output_filename_uses_stem(self, tmp_path: Path) -> None:
        """Output file name = {stem}.{format}."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "my_part.obj"
        src.write_bytes(b"v 0 0 0")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = convert_mesh(src, "obj", out_dir)
        assert result.name == "my_part.obj"

    def test_unsupported_format_raises_value_error(self, tmp_path: Path) -> None:
        """Unsupported target format → ValueError with supported list."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "mesh.stl"
        src.write_bytes(b"data")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        with pytest.raises(ValueError, match="3mf.*glb.*obj.*stl"):
            convert_mesh(src, "xyz", out_dir)

    def test_unsupported_format_error_message(self, tmp_path: Path) -> None:
        """ValueError message includes the unsupported format name."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "mesh.stl"
        src.write_bytes(b"data")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        with pytest.raises(ValueError, match="xyz"):
            convert_mesh(src, "xyz", out_dir)

    def test_convert_obj_to_stl(self, tmp_path: Path) -> None:
        """OBJ → STL conversion via trimesh (mocked)."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "mesh.obj"
        src.write_bytes(b"v 0 0 0")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        mock_mesh = MagicMock()
        mock_trimesh = MagicMock()
        mock_trimesh.load.return_value = mock_mesh
        with patch.dict("sys.modules", {"trimesh": mock_trimesh}):
            result = convert_mesh(src, "stl", out_dir)

        assert result == out_dir / "mesh.stl"
        mock_trimesh.load.assert_called_once_with(str(src))
        mock_mesh.export.assert_called_once_with(str(out_dir / "mesh.stl"))

    def test_convert_stl_to_glb(self, tmp_path: Path) -> None:
        """STL → GLB conversion via trimesh (mocked)."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "part.stl"
        src.write_bytes(b"binary stl")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        mock_mesh = MagicMock()
        mock_trimesh = MagicMock()
        mock_trimesh.load.return_value = mock_mesh
        with patch.dict("sys.modules", {"trimesh": mock_trimesh}):
            result = convert_mesh(src, "glb", out_dir)

        assert result == out_dir / "part.glb"
        mock_mesh.export.assert_called_once_with(str(out_dir / "part.glb"))

    def test_convert_stl_to_3mf(self, tmp_path: Path) -> None:
        """STL → 3MF conversion via trimesh (mocked)."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "gear.stl"
        src.write_bytes(b"binary stl")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        mock_mesh = MagicMock()
        mock_trimesh = MagicMock()
        mock_trimesh.load.return_value = mock_mesh
        with patch.dict("sys.modules", {"trimesh": mock_trimesh}):
            result = convert_mesh(src, "3mf", out_dir)

        assert result == out_dir / "gear.3mf"
        mock_mesh.export.assert_called_once_with(str(out_dir / "gear.3mf"))

    def test_case_insensitive_format(self, tmp_path: Path) -> None:
        """Format string is lowercased before comparison."""
        from backend.core.mesh_converter import convert_mesh

        src = tmp_path / "mesh.stl"
        src.write_bytes(b"data")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # Same-format passthrough even when uppercase
        result = convert_mesh(src, "STL", out_dir)
        assert result == out_dir / "mesh.stl"


# =========================================================================
# Export API endpoint tests
# =========================================================================


class TestExportAPI:
    """Tests for GET /api/jobs/{job_id}/assets/{asset_key} endpoint."""

    @pytest.fixture()
    def asset_file(self, tmp_path: Path) -> Path:
        """Create a dummy asset file."""
        f = tmp_path / "watertight_mesh.obj"
        f.write_bytes(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3")
        return f

    @pytest.fixture()
    def mock_asset_registry(self, asset_file: Path) -> MagicMock:
        """Create a mock AssetRegistry with one entry."""
        from backend.graph.context import AssetEntry

        entry = AssetEntry(
            key="watertight_mesh",
            path=str(asset_file),
            format="obj",
            producer="mesh_healer",
        )
        registry = MagicMock()
        registry.get.return_value = entry
        registry.has.return_value = True
        return registry

    @pytest.fixture()
    def app_with_export(self):
        """Create a minimal FastAPI app with export route."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.api.routes.export import router

        app = FastAPI()
        app.include_router(router, prefix="/api")
        return TestClient(app)

    def test_export_original_format_returns_file(
        self, app_with_export, mock_asset_registry, asset_file,
    ) -> None:
        """No format param → return original file."""
        with patch(
            "backend.api.routes.export._get_asset_registry",
            return_value=mock_asset_registry,
        ):
            resp = app_with_export.get("/api/jobs/job-123/assets/watertight_mesh")

        assert resp.status_code == 200
        assert resp.content == asset_file.read_bytes()

    def test_export_with_format_conversion(
        self, app_with_export, mock_asset_registry, asset_file, tmp_path,
    ) -> None:
        """format=stl → convert and return."""
        converted = tmp_path / "converted" / "watertight_mesh.stl"
        converted.parent.mkdir(parents=True, exist_ok=True)
        converted.write_bytes(b"converted stl data")

        with (
            patch(
                "backend.api.routes.export._get_asset_registry",
                return_value=mock_asset_registry,
            ),
            patch(
                "backend.api.routes.export.convert_mesh",
                return_value=converted,
            ) as mock_convert,
        ):
            resp = app_with_export.get(
                "/api/jobs/job-123/assets/watertight_mesh?format=stl"
            )

        assert resp.status_code == 200
        assert resp.content == b"converted stl data"
        mock_convert.assert_called_once()

    def test_export_unsupported_format_returns_400(
        self, app_with_export, mock_asset_registry,
    ) -> None:
        """Unsupported format → 400."""
        with (
            patch(
                "backend.api.routes.export._get_asset_registry",
                return_value=mock_asset_registry,
            ),
            patch(
                "backend.api.routes.export.convert_mesh",
                side_effect=ValueError("Unsupported format: xyz"),
            ),
        ):
            resp = app_with_export.get(
                "/api/jobs/job-123/assets/watertight_mesh?format=xyz"
            )

        assert resp.status_code == 400

    def test_export_job_not_found_returns_404(self, app_with_export) -> None:
        """Non-existent job → 404."""
        with patch(
            "backend.api.routes.export._get_asset_registry",
            return_value=None,
        ):
            resp = app_with_export.get(
                "/api/jobs/nonexistent/assets/watertight_mesh"
            )

        assert resp.status_code == 404

    def test_export_asset_not_found_returns_404(
        self, app_with_export,
    ) -> None:
        """Non-existent asset key → 404."""
        registry = MagicMock()
        registry.has.return_value = False

        with patch(
            "backend.api.routes.export._get_asset_registry",
            return_value=registry,
        ):
            resp = app_with_export.get(
                "/api/jobs/job-123/assets/nonexistent_asset"
            )

        assert resp.status_code == 404

    def test_export_missing_file_returns_404(
        self, app_with_export, tmp_path,
    ) -> None:
        """Asset registered but file missing on disk → 404."""
        from backend.graph.context import AssetEntry

        entry = AssetEntry(
            key="mesh",
            path=str(tmp_path / "gone.obj"),
            format="obj",
            producer="healer",
        )
        registry = MagicMock()
        registry.has.return_value = True
        registry.get.return_value = entry

        with patch(
            "backend.api.routes.export._get_asset_registry",
            return_value=registry,
        ):
            resp = app_with_export.get("/api/jobs/job-123/assets/mesh")

        assert resp.status_code == 404
