"""Tests for cross-section analysis validation."""
from __future__ import annotations

import pytest

from backend.knowledge.part_types import BaseBodySpec, DimensionLayer, DrawingSpec, PartType


def _make_stepped_spec() -> DrawingSpec:
    """Stepped shaft: d1=100 h1=30, d2=60 h2=40."""
    return DrawingSpec(
        part_type=PartType.ROTATIONAL_STEPPED,
        description="Stepped shaft",
        base_body=BaseBodySpec(
            method="revolve",
            profile=[
                DimensionLayer(diameter=100, height=30),
                DimensionLayer(diameter=60, height=40),
            ],
        ),
    )


class TestCrossSectionAnalysis:
    def test_stepped_cylinder(self, tmp_path) -> None:
        """Build stepped cylinder d=100 h=30 + d=60 h=40, verify cross-sections."""
        import cadquery as cq

        step_path = str(tmp_path / "stepped.step")
        result = (
            cq.Workplane("XY")
            .circle(50)
            .extrude(30)
            .faces(">Z")
            .workplane()
            .circle(30)
            .extrude(40)
        )
        cq.exporters.export(result, step_path)

        from backend.core.validators import cross_section_analysis

        spec = _make_stepped_spec()
        analysis = cross_section_analysis(step_path, spec)

        assert analysis.error == ""
        assert len(analysis.sections) == 2
        # Layer 0: mid_h=15, expected d=100
        assert abs(analysis.sections[0].measured_diameter - 100) < 5
        assert analysis.sections[0].within_tolerance is True
        # Layer 1: mid_h=30+20=50, expected d=60
        assert abs(analysis.sections[1].measured_diameter - 60) < 5
        assert analysis.sections[1].within_tolerance is True

    def test_mismatched_diameter_detected(self, tmp_path) -> None:
        """Build wrong diameter, cross-section should detect mismatch."""
        import cadquery as cq

        step_path = str(tmp_path / "wrong.step")
        # Wrong: base d=80 instead of spec's 100
        result = (
            cq.Workplane("XY")
            .circle(40)
            .extrude(30)
            .faces(">Z")
            .workplane()
            .circle(30)
            .extrude(40)
        )
        cq.exporters.export(result, step_path)

        from backend.core.validators import cross_section_analysis

        spec = _make_stepped_spec()
        analysis = cross_section_analysis(step_path, spec)
        # First layer: actual d=80 vs expected d=100 → >10% deviation
        assert any(not s.within_tolerance for s in analysis.sections)

    def test_nonexistent_file(self) -> None:
        from backend.core.validators import cross_section_analysis

        spec = _make_stepped_spec()
        analysis = cross_section_analysis("/nonexistent.step", spec)
        assert analysis.error != ""

    def test_empty_profile(self) -> None:
        from backend.core.validators import cross_section_analysis

        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="No profile",
            base_body=BaseBodySpec(method="extrude"),
        )
        analysis = cross_section_analysis("/any/path.step", spec)
        assert analysis.error != ""
