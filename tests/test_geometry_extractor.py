"""Tests for geometry_extractor — STEP and Mesh extraction paths."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# T1: STEP path tests
# ---------------------------------------------------------------------------


def test_extract_from_step_returns_geometry_info():
    """STEP file extraction returns all required geometry_info fields."""
    mock_cq = MagicMock()
    mock_shape = MagicMock()
    mock_shape.BoundingBox.return_value = MagicMock(
        xlen=50.0, ylen=30.0, zlen=20.0
    )
    mock_shape.Volume.return_value = 30000.0  # mm³ = 30 cm³
    mock_wp = MagicMock()
    mock_wp.val.return_value = mock_shape
    mock_cq.importers.importStep.return_value = mock_wp

    with patch.dict(sys.modules, {"cadquery": mock_cq}):
        from backend.core.geometry_extractor import extract_geometry_from_step

        result = extract_geometry_from_step("/fake/model.step")

    assert "bounding_box" in result
    assert result["bounding_box"] == {"x": 50.0, "y": 30.0, "z": 20.0}
    assert "volume_cm3" in result
    assert result["volume_cm3"] == pytest.approx(30.0, rel=0.01)
    assert "min_wall_thickness" in result
    assert "max_overhang_angle" in result
    assert "min_hole_diameter" in result


def test_extract_from_step_rounds_values():
    """Bounding box and volume values are properly rounded."""
    mock_cq = MagicMock()
    mock_shape = MagicMock()
    mock_shape.BoundingBox.return_value = MagicMock(
        xlen=50.123456, ylen=30.789012, zlen=20.345678
    )
    mock_shape.Volume.return_value = 31234.5678
    mock_wp = MagicMock()
    mock_wp.val.return_value = mock_shape
    mock_cq.importers.importStep.return_value = mock_wp

    with patch.dict(sys.modules, {"cadquery": mock_cq}):
        from backend.core.geometry_extractor import extract_geometry_from_step

        result = extract_geometry_from_step("/fake/model.step")

    assert result["bounding_box"]["x"] == 50.12
    assert result["bounding_box"]["y"] == 30.79
    assert result["bounding_box"]["z"] == 20.35
    assert result["volume_cm3"] == pytest.approx(31.2346, rel=0.01)


def test_extract_from_step_zero_volume():
    """Handle zero-volume shapes gracefully."""
    mock_cq = MagicMock()
    mock_shape = MagicMock()
    mock_shape.BoundingBox.return_value = MagicMock(
        xlen=0.0, ylen=0.0, zlen=0.0
    )
    mock_shape.Volume.return_value = 0.0
    mock_wp = MagicMock()
    mock_wp.val.return_value = mock_shape
    mock_cq.importers.importStep.return_value = mock_wp

    with patch.dict(sys.modules, {"cadquery": mock_cq}):
        from backend.core.geometry_extractor import extract_geometry_from_step

        result = extract_geometry_from_step("/fake/empty.step")

    assert result["bounding_box"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert result["volume_cm3"] == 0.0


# ---------------------------------------------------------------------------
# T2: Mesh path tests
# ---------------------------------------------------------------------------


def _make_mock_trimesh() -> MagicMock:
    """Create a mock trimesh module."""
    mock_trimesh = MagicMock()
    return mock_trimesh


def test_extract_from_mesh_returns_geometry_info():
    """Mesh extraction returns geometry_info with wall_thickness=None."""
    mock_trimesh = _make_mock_trimesh()
    mock_mesh = MagicMock()
    mock_mesh.bounds = np.array([[-25, -15, -10], [25, 15, 10]])
    mock_mesh.volume = 30000.0
    mock_mesh.is_watertight = True
    mock_mesh.face_normals = np.array([[0, 0, 1]])  # upward only
    mock_trimesh.load.return_value = mock_mesh

    with patch.dict(sys.modules, {"trimesh": mock_trimesh}):
        from backend.core.geometry_extractor import extract_geometry_from_mesh

        result = extract_geometry_from_mesh("/fake/model.glb")

    assert result["bounding_box"] == {"x": 50.0, "y": 30.0, "z": 20.0}
    assert result["volume_cm3"] == pytest.approx(30.0, rel=0.01)
    assert result["min_wall_thickness"] is None


def test_extract_from_mesh_non_watertight():
    """Non-watertight mesh returns volume_cm3=None."""
    mock_trimesh = _make_mock_trimesh()
    mock_mesh = MagicMock()
    mock_mesh.bounds = np.array([[-10, -10, -10], [10, 10, 10]])
    mock_mesh.volume = 5000.0
    mock_mesh.is_watertight = False
    mock_mesh.face_normals = np.array([[0, 0, 1]])
    mock_trimesh.load.return_value = mock_mesh

    with patch.dict(sys.modules, {"trimesh": mock_trimesh}):
        from backend.core.geometry_extractor import extract_geometry_from_mesh

        result = extract_geometry_from_mesh("/fake/open.stl")

    assert result["bounding_box"] == {"x": 20.0, "y": 20.0, "z": 20.0}
    assert result["volume_cm3"] is None


def test_extract_from_mesh_overhang_estimation():
    """Overhang angle is estimated from face normals."""
    mock_trimesh = _make_mock_trimesh()
    mock_mesh = MagicMock()
    mock_mesh.bounds = np.array([[0, 0, 0], [10, 10, 10]])
    mock_mesh.volume = 1000.0
    mock_mesh.is_watertight = True
    mock_mesh.face_normals = np.array([
        [0, 0, -1],            # 0° from -Z axis (straight down)
        [0, -0.707, -0.707],   # ~45° overhang
    ])
    mock_trimesh.load.return_value = mock_mesh

    with patch.dict(sys.modules, {"trimesh": mock_trimesh}):
        from backend.core.geometry_extractor import extract_geometry_from_mesh

        result = extract_geometry_from_mesh("/fake/overhang.glb")

    assert result["max_overhang_angle"] is not None
    assert result["max_overhang_angle"] == pytest.approx(45.0, abs=1.0)
