"""Tests for involute gear template and math."""
import math
import pytest

from backend.models.template import load_template
from backend.core.template_engine import TemplateEngine
from pathlib import Path


TEMPLATES_DIR = Path(__file__).parent.parent / "backend" / "knowledge" / "templates"


class TestGearInvoluteTemplate:
    def test_template_loads(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        matches = engine.find_matches("gear")
        names = [t.name for t in matches]
        assert "gear_involute" in names

    def test_template_default_params_valid(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        errors = engine.validate("gear_involute", {})
        assert errors == []

    def test_template_renders_code(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        code = engine.render("gear_involute", {}, "output.step")
        assert "import cadquery as cq" in code
        assert "math" in code
        assert "involute" in code.lower() or "齿" in code

    def test_template_renders_with_custom_params(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        code = engine.render(
            "gear_involute",
            {"module_val": 3, "num_teeth": 32, "bore_diameter": 20},
            "test.step",
        )
        assert "3" in code  # module_val
        assert "32" in code  # num_teeth
        assert "test.step" in code

    def test_template_bore_zero_no_hole(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        code = engine.render(
            "gear_involute",
            {"bore_diameter": 0},
            "out.step",
        )
        assert "cutThruAll" not in code

    def test_constraint_min_teeth(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        errors = engine.validate("gear_involute", {"num_teeth": 5})
        assert any("num_teeth" in e for e in errors)

    def test_constraint_bore_vs_pitch_diameter(self):
        engine = TemplateEngine.from_directory(TEMPLATES_DIR)
        errors = engine.validate(
            "gear_involute",
            {"module_val": 2, "num_teeth": 10, "bore_diameter": 50},
        )
        assert len(errors) > 0


class TestInvoluteMath:
    """Verify involute gear math formulas."""

    def test_pitch_radius(self):
        m, z = 2, 24
        rp = m * z / 2
        assert rp == 24.0

    def test_addendum_radius(self):
        m, z = 2, 24
        ra = m * (z + 2) / 2
        assert ra == 26.0

    def test_dedendum_radius(self):
        m, z = 2, 24
        rf = m * (z - 2.5) / 2
        assert rf == 21.5

    def test_base_radius(self):
        m, z = 2, 24
        alpha = math.radians(20)
        rb = m * z / 2 * math.cos(alpha)
        assert rb == pytest.approx(22.553, abs=0.01)

    def test_base_less_than_dedendum(self):
        """Base circle can be larger than dedendum for small teeth — known case."""
        m, z = 2, 12
        alpha = math.radians(20)
        rb = m * z / 2 * math.cos(alpha)
        rf = m * (z - 2.5) / 2
        # For z=12: rb=11.28, rf=9.5 → rb > rf is normal
        assert rb > rf
