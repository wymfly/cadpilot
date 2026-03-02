"""Tests for the PrintabilityChecker — all geometry info is pre-computed dicts."""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.printability import (
    PRESET_PROFILES,
    PrintabilityChecker,
)
from backend.models.printability import PrintProfile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def checker() -> PrintabilityChecker:
    return PrintabilityChecker()


def _full_geometry(
    *,
    wall: float = 1.5,
    overhang: float = 30.0,
    hole: float = 3.0,
    rib: float = 1.5,
    bbox: dict[str, float] | None = None,
    volume: float = 50.0,
) -> dict:
    """Build a complete geometry_info dict with sensible defaults."""
    return {
        "min_wall_thickness": wall,
        "max_overhang_angle": overhang,
        "min_hole_diameter": hole,
        "min_rib_thickness": rib,
        "bounding_box": bbox or {"x": 100, "y": 80, "z": 60},
        "volume_cm3": volume,
    }


# ---------------------------------------------------------------------------
# 1. Preset profiles
# ---------------------------------------------------------------------------


class TestPresetProfiles:
    def test_fdm_profile_loaded(self) -> None:
        p = PRESET_PROFILES["fdm_standard"]
        assert p.technology == "FDM"
        assert p.min_wall_thickness == 0.8
        assert p.build_volume == (220, 220, 250)

    def test_sla_profile_loaded(self) -> None:
        p = PRESET_PROFILES["sla_standard"]
        assert p.technology == "SLA"
        assert p.min_wall_thickness == 0.3
        assert p.min_hole_diameter == 0.5

    def test_sls_profile_loaded(self) -> None:
        p = PRESET_PROFILES["sls_standard"]
        assert p.technology == "SLS"
        assert p.max_overhang_angle == 90.0  # self-supporting


# ---------------------------------------------------------------------------
# 2. Wall thickness checks
# ---------------------------------------------------------------------------


class TestWallThickness:
    def test_wall_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(wall=1.0)
        result = checker.check(geo, "fdm_standard")
        wall_issues = [i for i in result.issues if i.check == "wall_thickness"]
        assert wall_issues == []

    def test_wall_fail(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(wall=0.5)
        result = checker.check(geo, "fdm_standard")
        wall_issues = [i for i in result.issues if i.check == "wall_thickness"]
        assert len(wall_issues) == 1
        assert wall_issues[0].severity == "error"
        assert wall_issues[0].value == 0.5
        assert wall_issues[0].threshold == 0.8

    def test_wall_at_boundary(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(wall=0.8)
        result = checker.check(geo, "fdm_standard")
        wall_issues = [i for i in result.issues if i.check == "wall_thickness"]
        assert wall_issues == []


# ---------------------------------------------------------------------------
# 3. Overhang checks
# ---------------------------------------------------------------------------


class TestOverhang:
    def test_overhang_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(overhang=30.0)
        result = checker.check(geo, "fdm_standard")
        oh_issues = [i for i in result.issues if i.check == "overhang"]
        assert oh_issues == []

    def test_overhang_fail(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(overhang=60.0)
        result = checker.check(geo, "fdm_standard")
        oh_issues = [i for i in result.issues if i.check == "overhang"]
        assert len(oh_issues) == 1
        assert oh_issues[0].severity == "warning"
        assert oh_issues[0].value == 60.0
        assert oh_issues[0].threshold == 45.0

    def test_overhang_at_boundary(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(overhang=45.0)
        result = checker.check(geo, "fdm_standard")
        oh_issues = [i for i in result.issues if i.check == "overhang"]
        assert oh_issues == []


# ---------------------------------------------------------------------------
# 4. Hole diameter checks
# ---------------------------------------------------------------------------


class TestHoleDiameter:
    def test_hole_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(hole=3.0)
        result = checker.check(geo, "fdm_standard")
        hole_issues = [i for i in result.issues if i.check == "hole_diameter"]
        assert hole_issues == []

    def test_hole_fail(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(hole=1.0)
        result = checker.check(geo, "fdm_standard")
        hole_issues = [i for i in result.issues if i.check == "hole_diameter"]
        assert len(hole_issues) == 1
        assert hole_issues[0].severity == "error"
        assert hole_issues[0].value == 1.0
        assert hole_issues[0].threshold == 2.0

    def test_hole_at_boundary(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(hole=2.0)
        result = checker.check(geo, "fdm_standard")
        hole_issues = [i for i in result.issues if i.check == "hole_diameter"]
        assert hole_issues == []


# ---------------------------------------------------------------------------
# 5. Rib thickness checks
# ---------------------------------------------------------------------------


class TestRibThickness:
    def test_rib_fail(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(rib=0.5)
        result = checker.check(geo, "fdm_standard")
        rib_issues = [i for i in result.issues if i.check == "rib_thickness"]
        assert len(rib_issues) == 1
        assert rib_issues[0].severity == "warning"
        assert rib_issues[0].value == 0.5
        assert rib_issues[0].threshold == 0.8

    def test_rib_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(rib=1.0)
        result = checker.check(geo, "fdm_standard")
        rib_issues = [i for i in result.issues if i.check == "rib_thickness"]
        assert rib_issues == []


# ---------------------------------------------------------------------------
# 6. Build volume checks
# ---------------------------------------------------------------------------


class TestBuildVolume:
    def test_build_volume_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(bbox={"x": 200, "y": 200, "z": 200})
        result = checker.check(geo, "fdm_standard")
        bv_issues = [i for i in result.issues if i.check == "build_volume"]
        assert bv_issues == []

    def test_build_volume_fail(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(bbox={"x": 300, "y": 100, "z": 100})
        result = checker.check(geo, "fdm_standard")
        bv_issues = [i for i in result.issues if i.check == "build_volume"]
        assert len(bv_issues) == 1
        assert bv_issues[0].severity == "error"
        assert "X" in bv_issues[0].message

    def test_build_volume_multiple_axes(
        self, checker: PrintabilityChecker
    ) -> None:
        geo = _full_geometry(bbox={"x": 300, "y": 300, "z": 300})
        result = checker.check(geo, "fdm_standard")
        bv_issues = [i for i in result.issues if i.check == "build_volume"]
        assert len(bv_issues) == 1
        assert "X" in bv_issues[0].message
        assert "Y" in bv_issues[0].message
        assert "Z" in bv_issues[0].message


# ---------------------------------------------------------------------------
# 7. Aggregated printability
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_all_pass(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry()
        result = checker.check(geo, "fdm_standard")
        assert result.printable is True
        assert result.issues == []
        assert result.profile == "fdm_standard"
        assert result.material_volume_cm3 == 50.0

    def test_error_makes_unprintable(
        self, checker: PrintabilityChecker
    ) -> None:
        geo = _full_geometry(wall=0.3)
        result = checker.check(geo, "fdm_standard")
        assert result.printable is False
        errors = [i for i in result.issues if i.severity == "error"]
        assert len(errors) >= 1

    def test_warning_still_printable(
        self, checker: PrintabilityChecker
    ) -> None:
        geo = _full_geometry(overhang=60.0)
        result = checker.check(geo, "fdm_standard")
        assert result.printable is True
        warnings = [i for i in result.issues if i.severity == "warning"]
        assert len(warnings) >= 1


# ---------------------------------------------------------------------------
# 8. Cross-profile comparison
# ---------------------------------------------------------------------------


class TestCrossProfile:
    def test_fdm_vs_sla_wall(self, checker: PrintabilityChecker) -> None:
        """0.5 mm wall fails FDM (0.8) but passes SLA (0.3)."""
        geo = _full_geometry(wall=0.5)
        fdm = checker.check(geo, "fdm_standard")
        sla = checker.check(geo, "sla_standard")
        assert fdm.printable is False
        assert sla.printable is True

    def test_fdm_vs_sls_overhang(self, checker: PrintabilityChecker) -> None:
        """60° overhang warns for FDM (45°) but not SLS (90°)."""
        geo = _full_geometry(overhang=60.0)
        fdm = checker.check(geo, "fdm_standard")
        sls = checker.check(geo, "sls_standard")
        oh_fdm = [i for i in fdm.issues if i.check == "overhang"]
        oh_sls = [i for i in sls.issues if i.check == "overhang"]
        assert len(oh_fdm) == 1
        assert oh_sls == []

    def test_sla_smaller_build_volume(
        self, checker: PrintabilityChecker
    ) -> None:
        """200 mm bbox fits FDM (220) but not SLA (145)."""
        geo = _full_geometry(bbox={"x": 200, "y": 100, "z": 100})
        fdm = checker.check(geo, "fdm_standard")
        sla = checker.check(geo, "sla_standard")
        assert fdm.printable is True
        assert sla.printable is False


# ---------------------------------------------------------------------------
# 9. Unknown profile
# ---------------------------------------------------------------------------


class TestUnknownProfile:
    def test_raises_value_error(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry()
        with pytest.raises(ValueError, match="Unknown profile"):
            checker.check(geo, "unknown_tech")

    def test_custom_profile_object(
        self, checker: PrintabilityChecker
    ) -> None:
        """Passing a PrintProfile instance directly works."""
        custom = PrintProfile(
            name="custom",
            technology="FDM",
            min_wall_thickness=1.0,
            max_overhang_angle=40.0,
            min_hole_diameter=1.5,
            min_rib_thickness=1.0,
            build_volume=(150, 150, 150),
        )
        geo = _full_geometry()
        result = checker.check(geo, custom)
        assert result.profile == "custom"


# ---------------------------------------------------------------------------
# 10. Missing geometry fields
# ---------------------------------------------------------------------------


class TestMissingFields:
    def test_empty_geometry(self, checker: PrintabilityChecker) -> None:
        result = checker.check({}, "fdm_standard")
        assert result.printable is True
        assert result.issues == []

    def test_partial_geometry(self, checker: PrintabilityChecker) -> None:
        geo = {"min_wall_thickness": 0.3}
        result = checker.check(geo, "fdm_standard")
        assert result.printable is False
        assert len(result.issues) == 1
        assert result.issues[0].check == "wall_thickness"

    def test_only_bbox(self, checker: PrintabilityChecker) -> None:
        geo = {"bounding_box": {"x": 100, "y": 80, "z": 60}}
        result = checker.check(geo, "fdm_standard")
        assert result.printable is True
        assert result.bounding_box == {"x": 100, "y": 80, "z": 60}

    def test_volume_passthrough(self, checker: PrintabilityChecker) -> None:
        geo = {"volume_cm3": 42.5}
        result = checker.check(geo, "fdm_standard")
        assert result.material_volume_cm3 == 42.5


# ---------------------------------------------------------------------------
# 11. Vertex analysis region computation
# ---------------------------------------------------------------------------


class TestVertexAnalysisRegion:
    """When _vertex_analysis is present, wall/overhang issues get a region."""

    @staticmethod
    def _make_vertex_analysis(
        n: int = 100,
        wall_risk_low_pct: float = 0.3,
        overhang_risk_low_pct: float = 0.2,
    ) -> dict:
        """Create mock vertex analysis data with some at-risk vertices."""
        rng = np.random.RandomState(42)
        vertices = rng.rand(n, 3) * 100  # random vertices in [0, 100]
        risk_wall = np.ones(n, dtype=np.float64)
        risk_overhang = np.ones(n, dtype=np.float64)

        # Make some vertices at risk (risk < 0.5)
        n_wall_risk = int(n * wall_risk_low_pct)
        n_oh_risk = int(n * overhang_risk_low_pct)
        risk_wall[:n_wall_risk] = rng.rand(n_wall_risk) * 0.3
        risk_overhang[:n_oh_risk] = rng.rand(n_oh_risk) * 0.3

        return {
            "vertices": vertices,
            "risk_wall": risk_wall,
            "risk_overhang": risk_overhang,
            "wall_thickness": np.ones(n) * 2.0,
            "overhang_angle": np.ones(n) * 30.0,
        }

    def test_wall_issue_has_region(self, checker: PrintabilityChecker) -> None:
        va = self._make_vertex_analysis()
        geo = _full_geometry(wall=0.5)
        geo["_vertex_analysis"] = va
        result = checker.check(geo, "fdm_standard")
        wall_issues = [i for i in result.issues if i.check == "wall_thickness"]
        assert len(wall_issues) == 1
        assert wall_issues[0].region is not None
        assert "center" in wall_issues[0].region
        assert "radius" in wall_issues[0].region
        assert len(wall_issues[0].region["center"]) == 3

    def test_overhang_issue_has_region(self, checker: PrintabilityChecker) -> None:
        va = self._make_vertex_analysis()
        geo = _full_geometry(overhang=60.0)
        geo["_vertex_analysis"] = va
        result = checker.check(geo, "fdm_standard")
        oh_issues = [i for i in result.issues if i.check == "overhang"]
        assert len(oh_issues) == 1
        assert oh_issues[0].region is not None
        assert oh_issues[0].region["radius"] > 0

    def test_no_vertex_analysis_no_region(self, checker: PrintabilityChecker) -> None:
        geo = _full_geometry(wall=0.5)
        result = checker.check(geo, "fdm_standard")
        wall_issues = [i for i in result.issues if i.check == "wall_thickness"]
        assert len(wall_issues) == 1
        assert wall_issues[0].region is None

    def test_hole_issue_no_region(self, checker: PrintabilityChecker) -> None:
        """Region is only computed for wall_thickness and overhang."""
        va = self._make_vertex_analysis()
        geo = _full_geometry(hole=1.0)
        geo["_vertex_analysis"] = va
        result = checker.check(geo, "fdm_standard")
        hole_issues = [i for i in result.issues if i.check == "hole_diameter"]
        assert len(hole_issues) == 1
        assert hole_issues[0].region is None
