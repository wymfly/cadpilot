"""Tests for the parametric YAML template library (Phase 3 Task 3.4).

Validates:
- Template directory exists with 13+ YAML files
- All 7 part types are covered
- Each template has params, constraints, and valid code_template
- Rendering with defaults produces valid Python (ast.parse)
- Default params pass validation (no constraint violations)
- TemplateEngine.from_directory loads all templates correctly
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.core.template_engine import TemplateEngine
from backend.models.template import load_all_templates

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "backend" / "knowledge" / "templates"

EXPECTED_PART_TYPES = {
    "rotational",
    "rotational_stepped",
    "plate",
    "bracket",
    "housing",
    "gear",
    "general",
}

# Part types with expected minimum template counts
EXPECTED_COUNTS = {
    "rotational": 2,
    "rotational_stepped": 2,
    "plate": 2,
    "bracket": 2,
    "housing": 2,
    "gear": 1,
    "general": 2,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def templates():
    """Load all templates from the library directory."""
    return load_all_templates(TEMPLATES_DIR)


@pytest.fixture(scope="module")
def engine():
    """Build a TemplateEngine from the library directory."""
    return TemplateEngine.from_directory(TEMPLATES_DIR)


# ---------------------------------------------------------------------------
# 1. Structure tests
# ---------------------------------------------------------------------------


class TestTemplateLibraryStructure:
    def test_templates_directory_exists(self) -> None:
        assert TEMPLATES_DIR.exists(), f"Templates directory not found: {TEMPLATES_DIR}"
        assert TEMPLATES_DIR.is_dir()

    def test_at_least_13_templates(self, templates) -> None:
        assert len(templates) >= 13, f"Expected >= 13 templates, got {len(templates)}"

    def test_all_part_types_covered(self, templates) -> None:
        found_types = {t.part_type for t in templates}
        for pt in EXPECTED_PART_TYPES:
            assert pt in found_types, f"Part type '{pt}' not covered by any template"

    def test_each_template_has_params(self, templates) -> None:
        for t in templates:
            assert len(t.params) >= 1, (
                f"Template '{t.name}' has no params"
            )
            # Each param must have range_min, range_max, and default
            for p in t.params:
                if p.param_type in ("float", "int"):
                    assert p.range_min is not None, (
                        f"Template '{t.name}' param '{p.name}' missing range_min"
                    )
                    assert p.range_max is not None, (
                        f"Template '{t.name}' param '{p.name}' missing range_max"
                    )
                assert p.default is not None, (
                    f"Template '{t.name}' param '{p.name}' missing default"
                )

    def test_each_template_has_constraints(self, templates) -> None:
        for t in templates:
            assert len(t.constraints) >= 1, (
                f"Template '{t.name}' has no constraints"
            )

    def test_each_template_has_code(self, templates) -> None:
        for t in templates:
            assert t.code_template.strip(), (
                f"Template '{t.name}' has empty code_template"
            )
            assert "import cadquery as cq" in t.code_template, (
                f"Template '{t.name}' code_template missing 'import cadquery as cq'"
            )


# ---------------------------------------------------------------------------
# 2. Rendering tests
# ---------------------------------------------------------------------------


class TestTemplateRendering:
    def test_each_template_renders_with_defaults(self, engine) -> None:
        """Verify rendered code contains import + export statements."""
        for t in engine.list_templates():
            code = engine.render(t.name, {})
            assert "import cadquery as cq" in code, (
                f"Template '{t.name}' rendered code missing cadquery import"
            )
            assert "cq.exporters.export" in code, (
                f"Template '{t.name}' rendered code missing export call"
            )

    def test_rendered_code_is_valid_python(self, engine) -> None:
        """ast.parse the rendered code — must not raise SyntaxError."""
        for t in engine.list_templates():
            code = engine.render(t.name, {})
            try:
                ast.parse(code)
            except SyntaxError as exc:
                pytest.fail(
                    f"Template '{t.name}' rendered code has syntax error: {exc}\n"
                    f"--- rendered code ---\n{code}"
                )


# ---------------------------------------------------------------------------
# 3. Validation tests
# ---------------------------------------------------------------------------


class TestTemplateValidation:
    def test_each_template_defaults_pass_validation(self, engine) -> None:
        """Validate with {} (use defaults) should return no errors."""
        for t in engine.list_templates():
            errors = engine.validate(t.name, {})
            assert errors == [], (
                f"Template '{t.name}' defaults fail validation: {errors}"
            )


# ---------------------------------------------------------------------------
# 4. Part type count tests
# ---------------------------------------------------------------------------


class TestPartTypeCounts:
    def test_rotational_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "rotational")
        assert count >= 2, f"Expected >= 2 rotational templates, got {count}"

    def test_rotational_stepped_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "rotational_stepped")
        assert count >= 2, f"Expected >= 2 rotational_stepped templates, got {count}"

    def test_plate_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "plate")
        assert count >= 2, f"Expected >= 2 plate templates, got {count}"

    def test_bracket_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "bracket")
        assert count >= 2, f"Expected >= 2 bracket templates, got {count}"

    def test_housing_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "housing")
        assert count >= 2, f"Expected >= 2 housing templates, got {count}"

    def test_gear_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "gear")
        assert count >= 1, f"Expected >= 1 gear templates, got {count}"

    def test_general_templates_count(self, templates) -> None:
        count = sum(1 for t in templates if t.part_type == "general")
        assert count >= 2, f"Expected >= 2 general templates, got {count}"


# ---------------------------------------------------------------------------
# 5. Engine loading integration
# ---------------------------------------------------------------------------


class TestEngineLoading:
    def test_engine_loads_all_templates(self, engine) -> None:
        assert len(engine.list_templates()) >= 13

    def test_engine_find_matches(self, engine) -> None:
        for pt, expected_min in EXPECTED_COUNTS.items():
            matches = engine.find_matches(pt)
            assert len(matches) >= expected_min, (
                f"find_matches('{pt}') returned {len(matches)}, expected >= {expected_min}"
            )

    def test_engine_get_each_template(self, engine) -> None:
        for t in engine.list_templates():
            fetched = engine.get_template(t.name)
            assert fetched.name == t.name
            assert fetched.part_type == t.part_type
