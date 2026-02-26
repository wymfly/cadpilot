"""Tests for engineering standards API routes (Phase 4 Task 4.4).

Validates:
- GET    /standards           list categories
- GET    /standards/{cat}     get entries, unknown category
- POST   /standards/recommend valid, empty, unknown type
- POST   /standards/check     valid, violations
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

import backend.api.standards as std_api


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_tmp_standards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point API to a tmp directory with minimal test YAML files."""
    d = tmp_path / "standards"
    d.mkdir()

    (d / "bolts.yaml").write_text(
        textwrap.dedent("""\
            standards:
              - name: "M10"
                params:
                  nominal_diameter: 10.0
                  through_hole: 11.0
                  counterbore_dia: 17.5
        """),
        encoding="utf-8",
    )

    (d / "flanges.yaml").write_text(
        textwrap.dedent("""\
            standards:
              - name: "DN100"
                params:
                  nominal_diameter: 100
                  outer_diameter: 220.0
                  thickness: 20.0
                  pcd: 180.0
                  hole_count: 8
                  hole_diameter: 18.0
                  bore_diameter: 108.0
        """),
        encoding="utf-8",
    )

    (d / "tolerances.yaml").write_text(
        textwrap.dedent("""\
            standards:
              - name: "H7/h6"
                params:
                  fit_type: "clearance"
                  hole_upper_deviation: 0.021
        """),
        encoding="utf-8",
    )

    (d / "keyways.yaml").write_text(
        textwrap.dedent("""\
            standards:
              - name: "d17-22"
                params:
                  shaft_diameter_min: 17.0
                  shaft_diameter_max: 22.0
                  key_width: 6.0
                  shaft_groove_depth: 3.5
        """),
        encoding="utf-8",
    )

    (d / "gears.yaml").write_text(
        textwrap.dedent("""\
            standards:
              - name: "m2"
                params:
                  module: 2.0
                  pressure_angle: 20.0
                  min_teeth: 14
                  max_teeth: 80
        """),
        encoding="utf-8",
    )

    monkeypatch.setattr(std_api, "_STANDARDS_DIR", d)


# ---------------------------------------------------------------------------
# GET /standards — list categories
# ---------------------------------------------------------------------------


class TestListCategories:
    def test_returns_five_categories(self) -> None:
        result = asyncio.run(std_api.list_categories())
        assert len(result) == 5
        assert set(result) == {"bolt", "flange", "tolerance", "keyway", "gear"}


# ---------------------------------------------------------------------------
# GET /standards/{category} — get entries
# ---------------------------------------------------------------------------


class TestGetCategory:
    def test_get_bolt_entries(self) -> None:
        result = asyncio.run(std_api.get_category("bolt"))
        assert len(result) == 1
        assert result[0]["name"] == "M10"
        assert result[0]["params"]["through_hole"] == 11.0

    def test_get_flange_entries(self) -> None:
        result = asyncio.run(std_api.get_category("flange"))
        assert len(result) == 1
        assert result[0]["name"] == "DN100"

    def test_unknown_category_empty(self) -> None:
        result = asyncio.run(std_api.get_category("nonexistent"))
        assert result == []


# ---------------------------------------------------------------------------
# POST /standards/recommend
# ---------------------------------------------------------------------------


class TestRecommend:
    def test_flange_recommendation(self) -> None:
        req = std_api.RecommendRequest(
            part_type="rotational",
            known_params={"outer_diameter": 220.0},
        )
        result = asyncio.run(std_api.recommend_params(req))
        names = {r.param_name for r in result.recommendations}
        assert "thickness" in names
        assert "pcd" in names

    def test_bolt_recommendation(self) -> None:
        req = std_api.RecommendRequest(
            part_type="rotational",
            known_params={"outer_diameter": 220.0, "bolt_size": 10.0},
        )
        result = asyncio.run(std_api.recommend_params(req))
        bolt_recs = [r for r in result.recommendations if r.param_name == "through_hole"]
        assert len(bolt_recs) == 1
        assert bolt_recs[0].value == 11.0

    def test_unknown_type_empty(self) -> None:
        req = std_api.RecommendRequest(
            part_type="unknown",
            known_params={"x": 1.0},
        )
        result = asyncio.run(std_api.recommend_params(req))
        assert result.recommendations == []

    def test_empty_params(self) -> None:
        req = std_api.RecommendRequest(
            part_type="rotational",
            known_params={},
        )
        result = asyncio.run(std_api.recommend_params(req))
        assert result.recommendations == []


# ---------------------------------------------------------------------------
# POST /standards/check
# ---------------------------------------------------------------------------


class TestCheck:
    def test_valid_params(self) -> None:
        req = std_api.CheckRequest(
            part_type="rotational",
            params={"outer_diameter": 220.0, "bore_diameter": 108.0, "pcd": 180.0},
        )
        result = asyncio.run(std_api.check_constraints(req))
        assert result.valid is True
        assert result.violations == []

    def test_bore_exceeds_od(self) -> None:
        req = std_api.CheckRequest(
            part_type="rotational",
            params={"outer_diameter": 50.0, "bore_diameter": 60.0},
        )
        result = asyncio.run(std_api.check_constraints(req))
        assert result.valid is False
        assert len(result.violations) >= 1

    def test_pcd_exceeds_od(self) -> None:
        req = std_api.CheckRequest(
            part_type="rotational",
            params={"outer_diameter": 100.0, "pcd": 120.0},
        )
        result = asyncio.run(std_api.check_constraints(req))
        assert result.valid is False
        assert any("pcd" in v.constraint for v in result.violations)

    def test_empty_params_valid(self) -> None:
        req = std_api.CheckRequest(
            part_type="rotational",
            params={},
        )
        result = asyncio.run(std_api.check_constraints(req))
        assert result.valid is True

    def test_gear_constraints(self) -> None:
        req = std_api.CheckRequest(
            part_type="gear",
            params={"module": 2.0, "teeth": 10},
        )
        result = asyncio.run(std_api.check_constraints(req))
        assert result.valid is False
        assert any("teeth" in v.constraint for v in result.violations)
