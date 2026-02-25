"""Tests for the static code parameter validator."""

from __future__ import annotations

import textwrap

import pytest

from cad3dify.knowledge.part_types import (
    BaseBodySpec,
    BoreSpec,
    DimensionLayer,
    DrawingSpec,
    PartType,
)
from cad3dify.v2.validators import (
    BBoxResult,
    ValidationResult,
    collect_spec_values,
    extract_numeric_assignments,
    validate_bounding_box,
    validate_code_params,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_spec(
    *,
    diameters: list[float] | None = None,
    heights: list[float] | None = None,
    bore_diameter: float | None = None,
    features: list[dict] | None = None,
) -> DrawingSpec:
    """Build a minimal DrawingSpec for testing."""
    profile = []
    if diameters and heights:
        for d, h in zip(diameters, heights):
            profile.append(DimensionLayer(diameter=d, height=h))

    bore = BoreSpec(diameter=bore_diameter) if bore_diameter else None

    return DrawingSpec(
        part_type=PartType.ROTATIONAL_STEPPED,
        description="Test stepped shaft",
        base_body=BaseBodySpec(
            method="revolve",
            profile=profile,
            bore=bore,
        ),
        features=features or [],
    )


# A realistic CadQuery code snippet that matches the default spec.
_CORRECT_CODE = textwrap.dedent("""\
    import cadquery as cq

    # -- dimensions --
    d1, h1 = 100, 30
    d2, h2 = 80, 50
    bore_d = 25

    # bolt pattern
    bolt_count = 6
    bolt_diameter = 10
    bolt_pcd = 70

    result = (
        cq.Workplane("XY")
        .circle(d1 / 2).extrude(h1)
        .faces(">Z").workplane()
        .circle(d2 / 2).extrude(h2)
        .faces("<Z").workplane()
        .hole(bore_d)
        .faces(">Z").workplane()
        .polarArray(bolt_pcd / 2, 0, 360, bolt_count)
        .circle(bolt_diameter / 2).cutThruAll()
    )

    cq.exporters.export(result, "output.step")
""")


def _default_spec() -> DrawingSpec:
    return _make_spec(
        diameters=[100, 80],
        heights=[30, 50],
        bore_diameter=25,
        features=[{"type": "hole_pattern", "count": 6, "diameter": 10, "pcd": 70}],
    )


# ---------------------------------------------------------------------------
# Test: AST extraction
# ---------------------------------------------------------------------------


class TestExtractNumericAssignments:
    def test_simple_assignments(self) -> None:
        code = "x = 100\ny = 3.14\nname = 'hello'"
        result = extract_numeric_assignments(code)
        assert result == {"x": 100.0, "y": 3.14}

    def test_tuple_unpacking(self) -> None:
        code = "a, b, c = 1, 2, 3"
        result = extract_numeric_assignments(code)
        assert result == {"a": 1.0, "b": 2.0, "c": 3.0}

    def test_mixed(self) -> None:
        code = "d1, h1 = 100, 30\nbore_d = 25"
        result = extract_numeric_assignments(code)
        assert result == {"d1": 100.0, "h1": 30.0, "bore_d": 25.0}

    def test_syntax_error_returns_empty(self) -> None:
        code = "this is not valid python @@!!"
        result = extract_numeric_assignments(code)
        assert result == {}

    def test_negative_number(self) -> None:
        code = "offset = -5"
        result = extract_numeric_assignments(code)
        assert result == {"offset": -5.0}


# ---------------------------------------------------------------------------
# Test: Spec collection
# ---------------------------------------------------------------------------


class TestCollectSpecValues:
    def test_profile_and_bore(self) -> None:
        spec = _default_spec()
        values = collect_spec_values(spec)
        assert values["profile_0_diameter"] == 100
        assert values["profile_1_height"] == 50
        assert values["bore_diameter"] == 25

    def test_features(self) -> None:
        spec = _default_spec()
        values = collect_spec_values(spec)
        assert values["feature_0_count"] == 6
        assert values["feature_0_diameter"] == 10
        assert values["feature_0_pcd"] == 70

    def test_no_bore(self) -> None:
        spec = _make_spec(diameters=[100], heights=[30])
        values = collect_spec_values(spec)
        assert "bore_diameter" not in values


# ---------------------------------------------------------------------------
# Test: Full validation — 4 required scenarios
# ---------------------------------------------------------------------------


class TestValidateCodeParams:
    def test_correct_code_passes(self) -> None:
        """Correct code passes validation with zero mismatches."""
        result = validate_code_params(_CORRECT_CODE, _default_spec())
        assert result.passed is True
        assert result.mismatches == []
        assert len(result.extracted_values) > 0

    def test_wrong_diameter_fails(self) -> None:
        """Wrong diameter (80 vs expected 100) produces a hard mismatch."""
        wrong_code = _CORRECT_CODE.replace("d1, h1 = 100, 30", "d1, h1 = 80, 30")
        result = validate_code_params(wrong_code, _default_spec())
        assert result.passed is False
        assert len(result.mismatches) > 0
        # At least one mismatch should mention the expected diameter
        mismatch_text = " ".join(result.mismatches)
        assert "100" in mismatch_text

    def test_missing_bore_is_warning(self) -> None:
        """Missing bore is a warning, not a hard fail."""
        code_no_bore = _CORRECT_CODE.replace("bore_d = 25", "# bore removed")
        result = validate_code_params(code_no_bore, _default_spec())
        assert result.passed is True  # soft — not a hard fail
        assert len(result.warnings) > 0
        warning_text = " ".join(result.warnings)
        assert "bore" in warning_text.lower()

    def test_values_within_tolerance_pass(self) -> None:
        """Values within 5% tolerance still pass."""
        # 100 * 1.04 = 104 → within 5%
        tolerant_code = _CORRECT_CODE.replace(
            "d1, h1 = 100, 30", "d1, h1 = 104, 31"
        )
        result = validate_code_params(tolerant_code, _default_spec())
        assert result.passed is True
        assert result.mismatches == []

    def test_values_outside_tolerance_fail(self) -> None:
        """Values beyond 5% tolerance produce a hard mismatch."""
        # 100 → 110 is 10% off — should fail
        bad_code = _CORRECT_CODE.replace(
            "d1, h1 = 100, 30", "d1, h1 = 110, 30"
        )
        result = validate_code_params(bad_code, _default_spec())
        assert result.passed is False

    def test_empty_code(self) -> None:
        """Empty code string with spec expectations → fails gracefully."""
        result = validate_code_params("", _default_spec())
        assert result.passed is False
        assert result.extracted_values == {}


# ---------------------------------------------------------------------------
# Test: Bounding-box validation
# ---------------------------------------------------------------------------


class TestBoundingBox:
    def test_matching_bbox_passes(self) -> None:
        dims = {"max_diameter": 100, "total_height": 30}
        actual_bbox = (100.0, 100.0, 30.0)
        result = validate_bounding_box(actual_bbox, dims)
        assert result.passed is True

    def test_wrong_height_fails(self) -> None:
        dims = {"max_diameter": 100, "total_height": 30}
        actual_bbox = (100.0, 100.0, 10.0)
        result = validate_bounding_box(actual_bbox, dims)
        assert result.passed is False

    def test_partial_dims_ok(self) -> None:
        dims = {"total_height": 30}
        actual_bbox = (80.0, 80.0, 30.0)
        result = validate_bounding_box(actual_bbox, dims)
        assert result.passed is True

    def test_within_tolerance_passes(self) -> None:
        dims = {"max_diameter": 100, "total_height": 30}
        actual_bbox = (95.0, 95.0, 28.0)  # within 10%
        result = validate_bounding_box(actual_bbox, dims)
        assert result.passed is True

    def test_empty_dims_passes(self) -> None:
        actual_bbox = (100.0, 100.0, 30.0)
        result = validate_bounding_box(actual_bbox, {})
        assert result.passed is True
