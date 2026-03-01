"""Tests for ParametricTemplateEngine (Phase 3 Task 3.3).

Validates:
- TemplateEngine(templates=[...]) constructor
- TemplateEngine.from_directory(path) class method
- list_templates / get_template / find_matches lookup
- render with params, defaults, output_filename, unknown template
- validate — valid params, out of range, constraint violation, eval error
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.template import ParamDefinition, ParametricTemplate
from backend.core.template_engine import TemplateEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flange_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="flange_disk",
        display_name="法兰盘",
        part_type="rotational",
        description="标准法兰盘",
        params=[
            ParamDefinition(
                name="diameter",
                display_name="直径",
                unit="mm",
                param_type="float",
                range_min=20,
                range_max=500,
                default=100,
            ),
            ParamDefinition(
                name="height",
                display_name="高度",
                unit="mm",
                param_type="float",
                range_min=5,
                range_max=100,
                default=20,
            ),
        ],
        constraints=["height < diameter"],
        code_template=(
            "import cadquery as cq\n"
            "diameter = {{ diameter }}\n"
            "height = {{ height }}\n"
            "result = cq.Workplane('XY').circle(diameter/2).extrude(height)\n"
            "cq.exporters.export(result, '{{ output_filename }}')"
        ),
    )


def _make_gear_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="spur_gear",
        display_name="直齿轮",
        part_type="gear",
        description="标准直齿轮",
        params=[
            ParamDefinition(
                name="module_val",
                display_name="模数",
                unit="mm",
                param_type="float",
                range_min=0.5,
                range_max=10,
                default=2,
            ),
            ParamDefinition(
                name="teeth",
                display_name="齿数",
                param_type="int",
                range_min=10,
                range_max=200,
                default=24,
            ),
        ],
        constraints=["teeth >= 10"],
        code_template=(
            "import cadquery as cq\n"
            "result = cq.Workplane('XY').circle({{ module_val }} * {{ teeth }} / 2).extrude(10)"
        ),
    )


def _make_bracket_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="l_bracket",
        display_name="L 形支架",
        part_type="bracket",
        description="L 形支架",
        params=[
            ParamDefinition(
                name="width",
                display_name="宽度",
                unit="mm",
                param_type="float",
                range_min=10,
                range_max=200,
                default=50,
            ),
        ],
        constraints=[],
        code_template="import cadquery as cq\nresult = cq.Workplane('XY').box({{ width }}, 10, 10)",
    )


def _build_engine() -> TemplateEngine:
    """Engine preloaded with flange + gear + bracket templates."""
    return TemplateEngine(
        templates=[_make_flange_template(), _make_gear_template(), _make_bracket_template()]
    )


# ---------------------------------------------------------------------------
# 1. Render
# ---------------------------------------------------------------------------


class TestTemplateEngineRender:
    def test_render_with_explicit_params(self) -> None:
        engine = _build_engine()
        code = engine.render("flange_disk", {"diameter": 200, "height": 30})
        assert "diameter = 200" in code
        assert "height = 30" in code
        # default output_filename
        assert "'output.step'" in code

    def test_render_uses_defaults_for_missing_params(self) -> None:
        engine = _build_engine()
        code = engine.render("flange_disk", {})
        assert "diameter = 100" in code
        assert "height = 20" in code

    def test_render_partial_override(self) -> None:
        engine = _build_engine()
        code = engine.render("flange_disk", {"diameter": 300})
        assert "diameter = 300" in code
        assert "height = 20" in code  # default

    def test_render_custom_output_filename(self) -> None:
        engine = _build_engine()
        code = engine.render("flange_disk", {}, output_filename="my_flange.step")
        assert "'my_flange.step'" in code

    def test_render_unknown_template_raises(self) -> None:
        engine = _build_engine()
        with pytest.raises(KeyError, match="not_exist"):
            engine.render("not_exist", {})

    def test_render_gear_template(self) -> None:
        engine = _build_engine()
        code = engine.render("spur_gear", {"module_val": 3, "teeth": 30})
        assert "3" in code
        assert "30" in code


# ---------------------------------------------------------------------------
# 2. Match / lookup
# ---------------------------------------------------------------------------


class TestTemplateEngineMatch:
    def test_find_matches_single(self) -> None:
        engine = _build_engine()
        matches = engine.find_matches("rotational")
        assert len(matches) == 1
        assert matches[0].name == "flange_disk"

    def test_find_matches_no_match(self) -> None:
        engine = _build_engine()
        matches = engine.find_matches("housing")
        assert matches == []

    def test_find_matches_multiple(self) -> None:
        flange1 = _make_flange_template()
        flange2 = _make_flange_template()
        flange2.name = "flange_disk_v2"
        engine = TemplateEngine(templates=[flange1, flange2])
        matches = engine.find_matches("rotational")
        assert len(matches) == 2

    def test_list_templates(self) -> None:
        engine = _build_engine()
        templates = engine.list_templates()
        assert len(templates) == 3
        names = {t.name for t in templates}
        assert names == {"flange_disk", "spur_gear", "l_bracket"}

    def test_list_templates_empty(self) -> None:
        engine = TemplateEngine()
        assert engine.list_templates() == []

    def test_get_template(self) -> None:
        engine = _build_engine()
        t = engine.get_template("flange_disk")
        assert t.name == "flange_disk"
        assert t.display_name == "法兰盘"

    def test_get_template_not_found(self) -> None:
        engine = _build_engine()
        with pytest.raises(KeyError, match="nonexistent"):
            engine.get_template("nonexistent")


# ---------------------------------------------------------------------------
# 3. Validate
# ---------------------------------------------------------------------------


class TestTemplateEngineValidate:
    def test_valid_params(self) -> None:
        engine = _build_engine()
        errors = engine.validate("flange_disk", {"diameter": 200, "height": 30})
        assert errors == []

    def test_valid_with_defaults(self) -> None:
        engine = _build_engine()
        errors = engine.validate("flange_disk", {})
        assert errors == []

    def test_out_of_range(self) -> None:
        engine = _build_engine()
        errors = engine.validate("flange_disk", {"diameter": 9999})
        assert len(errors) >= 1
        assert any("diameter" in e for e in errors)

    def test_constraint_violation(self) -> None:
        engine = _build_engine()
        # height=200, diameter=50 → height < diameter fails
        errors = engine.validate("flange_disk", {"diameter": 50, "height": 200})
        assert any("Constraint violation" in e for e in errors)
        assert any("height < diameter" in e for e in errors)

    def test_constraint_passes(self) -> None:
        engine = _build_engine()
        errors = engine.validate("flange_disk", {"diameter": 200, "height": 10})
        assert errors == []

    def test_multiple_errors(self) -> None:
        engine = _build_engine()
        # out of range AND constraint violation
        errors = engine.validate("flange_disk", {"diameter": 10, "height": 200})
        # diameter below min (20), height above max (100), constraint failure
        assert len(errors) >= 2

    def test_constraint_eval_error(self) -> None:
        """Constraint referencing undefined variable produces eval error."""
        tmpl = ParametricTemplate(
            name="bad_constraint",
            display_name="坏约束",
            part_type="general",
            params=[
                ParamDefinition(
                    name="x",
                    display_name="X",
                    param_type="float",
                    default=10,
                ),
            ],
            constraints=["x < undefined_var"],
        )
        engine = TemplateEngine(templates=[tmpl])
        errors = engine.validate("bad_constraint", {"x": 5})
        assert len(errors) == 1
        assert "Constraint evaluation error" in errors[0]

    def test_validate_unknown_template_raises(self) -> None:
        engine = _build_engine()
        with pytest.raises(KeyError, match="ghost"):
            engine.validate("ghost", {})

    def test_validate_gear_constraint(self) -> None:
        engine = _build_engine()
        # teeth=5 is below range_min=10 AND violates constraint teeth >= 10
        errors = engine.validate("spur_gear", {"teeth": 5})
        assert len(errors) >= 1

    def test_no_constraints_template(self) -> None:
        engine = _build_engine()
        errors = engine.validate("l_bracket", {"width": 100})
        assert errors == []

    def test_constraint_no_code_injection(self) -> None:
        """Constraint with __import__('os').system('echo pwned') must be rejected."""
        tmpl = ParametricTemplate(
            name="injection_test",
            display_name="注入测试",
            part_type="general",
            params=[
                ParamDefinition(
                    name="x",
                    display_name="X",
                    param_type="float",
                    default=10,
                ),
            ],
            constraints=["__import__('os').system('echo pwned')"],
        )
        engine = TemplateEngine(templates=[tmpl])
        errors = engine.validate("injection_test", {"x": 5})
        assert len(errors) == 1
        assert "Constraint evaluation error" in errors[0]

    def test_constraint_no_builtin_access(self) -> None:
        """Constraint with eval('1+1') == 2 must be rejected."""
        tmpl = ParametricTemplate(
            name="builtin_test",
            display_name="内置函数测试",
            part_type="general",
            params=[
                ParamDefinition(
                    name="x",
                    display_name="X",
                    param_type="float",
                    default=10,
                ),
            ],
            constraints=["eval('1+1') == 2"],
        )
        engine = TemplateEngine(templates=[tmpl])
        errors = engine.validate("builtin_test", {"x": 5})
        assert len(errors) == 1
        assert "Constraint evaluation error" in errors[0]


# ---------------------------------------------------------------------------
# 4. Load from directory
# ---------------------------------------------------------------------------


FLANGE_YAML = """\
name: flange_basic
display_name: 基础法兰盘
part_type: ROTATIONAL_STEPPED
description: 带螺栓孔的基础法兰盘
params:
  - name: outer_diameter
    display_name: 外径
    unit: mm
    param_type: float
    range_min: 20
    range_max: 500
    default: 100
  - name: bore_diameter
    display_name: 内孔直径
    unit: mm
    param_type: float
    range_min: 5
    range_max: 200
    default: 30
constraints:
  - "bore_diameter < outer_diameter"
code_template: |
  import cadquery as cq
  result = cq.Workplane("XY").circle({{ outer_diameter }} / 2).circle({{ bore_diameter }} / 2).extrude(10)
"""

GEAR_YAML = """\
name: spur_gear
display_name: 直齿轮
part_type: GEAR
description: 标准直齿轮
params:
  - name: module_val
    display_name: 模数
    param_type: float
    range_min: 0.5
    range_max: 10
    default: 2
  - name: teeth
    display_name: 齿数
    param_type: int
    range_min: 10
    range_max: 200
    default: 24
constraints:
  - "teeth >= 10"
code_template: |
  import cadquery as cq
  result = cq.Workplane("XY").circle({{ module_val }} * {{ teeth }} / 2).extrude(10)
"""


class TestTemplateEngineLoadFromDir:
    def test_from_directory(self, tmp_path: Path) -> None:
        (tmp_path / "01_flange.yaml").write_text(FLANGE_YAML, encoding="utf-8")
        (tmp_path / "02_gear.yaml").write_text(GEAR_YAML, encoding="utf-8")

        engine = TemplateEngine.from_directory(tmp_path)
        templates = engine.list_templates()
        assert len(templates) == 2
        names = {t.name for t in templates}
        assert names == {"flange_basic", "spur_gear"}

    def test_from_directory_empty(self, tmp_path: Path) -> None:
        engine = TemplateEngine.from_directory(tmp_path)
        assert engine.list_templates() == []

    def test_from_directory_get_and_render(self, tmp_path: Path) -> None:
        (tmp_path / "flange.yaml").write_text(FLANGE_YAML, encoding="utf-8")

        engine = TemplateEngine.from_directory(tmp_path)
        t = engine.get_template("flange_basic")
        assert t.part_type == "ROTATIONAL_STEPPED"

        code = engine.render("flange_basic", {"outer_diameter": 200, "bore_diameter": 50})
        assert "200" in code
        assert "50" in code

    def test_from_directory_find_matches(self, tmp_path: Path) -> None:
        (tmp_path / "01_flange.yaml").write_text(FLANGE_YAML, encoding="utf-8")
        (tmp_path / "02_gear.yaml").write_text(GEAR_YAML, encoding="utf-8")

        engine = TemplateEngine.from_directory(tmp_path)
        matches = engine.find_matches("GEAR")
        assert len(matches) == 1
        assert matches[0].name == "spur_gear"

    def test_from_directory_validate(self, tmp_path: Path) -> None:
        (tmp_path / "flange.yaml").write_text(FLANGE_YAML, encoding="utf-8")

        engine = TemplateEngine.from_directory(tmp_path)
        errors = engine.validate("flange_basic", {"outer_diameter": 200, "bore_diameter": 50})
        assert errors == []

        # Constraint violation: bore >= outer
        errors = engine.validate("flange_basic", {"outer_diameter": 30, "bore_diameter": 100})
        assert any("Constraint violation" in e for e in errors)
