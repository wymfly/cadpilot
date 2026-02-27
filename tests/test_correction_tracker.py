"""Tests for correction tracking — field-level diff + JSON persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.correction_tracker import (
    CORRECTIONS_DIR,
    compute_corrections,
    load_corrections,
    persist_corrections,
)


# ===================================================================
# compute_corrections
# ===================================================================


class TestComputeCorrections:
    def test_no_diff(self) -> None:
        """Identical dicts should produce zero corrections."""
        orig = {"part_type": "rotational", "overall_dimensions": {"d": 50}}
        conf = {"part_type": "rotational", "overall_dimensions": {"d": 50}}
        assert compute_corrections(orig, conf, "j1") == []

    def test_simple_field_change(self) -> None:
        """Single field change should produce one correction."""
        orig = {"part_type": "rotational"}
        conf = {"part_type": "plate"}
        result = compute_corrections(orig, conf, "j2")
        assert len(result) == 1
        assert result[0]["field_path"] == "part_type"
        assert result[0]["original_value"] == "rotational"
        assert result[0]["corrected_value"] == "plate"
        assert result[0]["job_id"] == "j2"

    def test_nested_field_change(self) -> None:
        """Nested dict field changes should produce dotted paths."""
        orig = {"overall_dimensions": {"d": 50, "h": 30}}
        conf = {"overall_dimensions": {"d": 52, "h": 30}}
        result = compute_corrections(orig, conf, "j3")
        assert len(result) == 1
        assert result[0]["field_path"] == "overall_dimensions.d"
        assert result[0]["original_value"] == "50"
        assert result[0]["corrected_value"] == "52"

    def test_multiple_changes(self) -> None:
        """Multiple field changes should produce multiple corrections."""
        orig = {"part_type": "rotational", "description": "old", "notes": ["a"]}
        conf = {"part_type": "plate", "description": "new", "notes": ["a"]}
        result = compute_corrections(orig, conf, "j4")
        assert len(result) == 2
        paths = {c["field_path"] for c in result}
        assert "part_type" in paths
        assert "description" in paths

    def test_added_field(self) -> None:
        """Field present in confirmed but not original should be tracked."""
        orig = {"part_type": "rotational"}
        conf = {"part_type": "rotational", "description": "new field"}
        result = compute_corrections(orig, conf, "j5")
        assert len(result) == 1
        assert result[0]["field_path"] == "description"
        assert result[0]["original_value"] == "None"
        assert result[0]["corrected_value"] == "new field"

    def test_removed_field(self) -> None:
        """Field present in original but not confirmed should be tracked."""
        orig = {"part_type": "rotational", "notes": ["important"]}
        conf = {"part_type": "rotational"}
        result = compute_corrections(orig, conf, "j6")
        assert len(result) == 1
        assert result[0]["field_path"] == "notes"

    def test_list_element_change(self) -> None:
        """List element changes should produce indexed paths."""
        orig = {"features": [{"type": "hole"}, {"type": "fillet"}]}
        conf = {"features": [{"type": "hole"}, {"type": "chamfer"}]}
        result = compute_corrections(orig, conf, "j7")
        assert len(result) == 1
        assert result[0]["field_path"] == "features[1].type"

    def test_list_length_change(self) -> None:
        """Different list lengths should track added/removed elements."""
        orig = {"notes": ["a", "b"]}
        conf = {"notes": ["a", "b", "c"]}
        result = compute_corrections(orig, conf, "j8")
        assert len(result) == 1
        assert result[0]["field_path"] == "notes[2]"
        assert result[0]["original_value"] == "None"
        assert result[0]["corrected_value"] == "c"

    def test_deeply_nested(self) -> None:
        """Deep nesting should produce correct dotted paths."""
        orig = {"base_body": {"bore": {"diameter": 10}}}
        conf = {"base_body": {"bore": {"diameter": 12}}}
        result = compute_corrections(orig, conf, "j9")
        assert len(result) == 1
        assert result[0]["field_path"] == "base_body.bore.diameter"

    def test_timestamp_present(self) -> None:
        """Each correction should have an ISO timestamp."""
        orig = {"x": 1}
        conf = {"x": 2}
        result = compute_corrections(orig, conf, "j10")
        assert len(result) == 1
        assert "timestamp" in result[0]
        # Should be ISO format
        assert "T" in result[0]["timestamp"]


# ===================================================================
# persist_corrections + load_corrections
# ===================================================================


class TestPersistCorrections:
    @pytest.fixture(autouse=True)
    def _cleanup(self) -> None:
        """Clean up test correction files after each test."""
        yield
        for p in CORRECTIONS_DIR.glob("test-persist-*.json"):
            p.unlink(missing_ok=True)

    def test_persist_creates_file(self) -> None:
        """persist_corrections should create a JSON file."""
        corrections = [
            {"job_id": "test-persist-1", "field_path": "x", "original_value": "1", "corrected_value": "2"},
        ]
        path = persist_corrections("test-persist-1", corrections)
        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["field_path"] == "x"

    def test_persist_creates_directory(self) -> None:
        """persist_corrections should create the directory if needed."""
        # Directory should exist (created by fixture or previous test)
        corrections = [{"job_id": "test-persist-2", "field_path": "y"}]
        path = persist_corrections("test-persist-2", corrections)
        assert path.parent.exists()

    def test_load_corrections(self) -> None:
        """load_corrections should read back persisted data."""
        corrections = [
            {"job_id": "test-persist-3", "field_path": "z", "original_value": "a", "corrected_value": "b"},
        ]
        persist_corrections("test-persist-3", corrections)
        loaded = load_corrections("test-persist-3")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["field_path"] == "z"

    def test_load_nonexistent(self) -> None:
        """load_corrections for nonexistent job should return None."""
        assert load_corrections("nonexistent-job") is None

    def test_persist_empty_list(self) -> None:
        """Persisting empty corrections should create a file with []."""
        path = persist_corrections("test-persist-4", [])
        assert path.exists()
        assert json.loads(path.read_text()) == []


# ===================================================================
# Integration: compute + persist roundtrip
# ===================================================================


class TestCorrectionRoundtrip:
    @pytest.fixture(autouse=True)
    def _cleanup(self) -> None:
        yield
        for p in CORRECTIONS_DIR.glob("roundtrip-*.json"):
            p.unlink(missing_ok=True)

    def test_full_roundtrip(self) -> None:
        """compute → persist → load should preserve all correction data."""
        orig = {
            "part_type": "rotational",
            "overall_dimensions": {"d": 50, "h": 30},
            "base_body": {"method": "revolve"},
        }
        conf = {
            "part_type": "rotational",
            "overall_dimensions": {"d": 52, "h": 30},
            "base_body": {"method": "revolve"},
        }
        corrections = compute_corrections(orig, conf, "roundtrip-1")
        assert len(corrections) == 1

        persist_corrections("roundtrip-1", corrections)
        loaded = load_corrections("roundtrip-1")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["field_path"] == "overall_dimensions.d"
        assert loaded[0]["original_value"] == "50"
        assert loaded[0]["corrected_value"] == "52"
