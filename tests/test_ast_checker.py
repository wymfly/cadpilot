"""Tests for AST pre-check and CadQuery API whitelist."""

from __future__ import annotations

import textwrap

import pytest

from backend.core.ast_checker import AstCheckResult, ast_pre_check
from backend.core.api_whitelist import (
    BLOCKED_APIS,
    CADQUERY_WHITELIST,
    get_whitelist_prompt_section,
)


# ---------------------------------------------------------------------------
# TestAstPreCheck
# ---------------------------------------------------------------------------


class TestAstPreCheck:
    def test_valid_code_passes(self) -> None:
        """Valid CadQuery code with export statement passes."""
        code = textwrap.dedent("""\
            import cadquery as cq

            diameter = 100
            height = 30

            result = cq.Workplane("XY").circle(diameter / 2).extrude(height)
            cq.exporters.export(result, "output.step")
        """)
        result = ast_pre_check(code)
        assert result.passed is True
        assert result.errors == []

    def test_missing_export_fails(self) -> None:
        """Code without export statement fails."""
        code = textwrap.dedent("""\
            import cadquery as cq

            result = cq.Workplane("XY").box(10, 10, 10)
        """)
        result = ast_pre_check(code)
        assert result.passed is False
        assert any("export" in e.lower() for e in result.errors)

    def test_syntax_error_fails(self) -> None:
        """Invalid Python syntax fails."""
        code = "def foo(:\n    pass"
        result = ast_pre_check(code)
        assert result.passed is False
        assert any("syntax" in e.lower() for e in result.errors)

    def test_blocked_import_fails(self) -> None:
        """Code with blocked import (os) fails."""
        code = textwrap.dedent("""\
            import os
            import cadquery as cq

            result = cq.Workplane("XY").box(10, 10, 10)
            cq.exporters.export(result, "output.step")
        """)
        result = ast_pre_check(code)
        assert result.passed is False
        assert any("os" in e for e in result.errors)

    def test_blocked_api_call_fails(self) -> None:
        """Code calling blocked API (show_object) fails."""
        code = textwrap.dedent("""\
            import cadquery as cq

            result = cq.Workplane("XY").box(10, 10, 10)
            show_object(result)
            cq.exporters.export(result, "output.step")
        """)
        result = ast_pre_check(code)
        assert result.passed is False
        assert any("show_object" in e for e in result.errors)

    def test_blocked_api_attribute_call_fails(self) -> None:
        """Code calling blocked API as attribute (obj.debug) fails."""
        code = textwrap.dedent("""\
            import cadquery as cq

            result = cq.Workplane("XY").box(10, 10, 10)
            cq.debug(result)
            cq.exporters.export(result, "output.step")
        """)
        result = ast_pre_check(code)
        assert result.passed is False
        assert any("debug" in e for e in result.errors)

    def test_undefined_export_variable_warns(self) -> None:
        """Export call with undefined variable produces a warning."""
        code = textwrap.dedent("""\
            import cadquery as cq

            cq.exporters.export(undefined_var, "output.step")
        """)
        result = ast_pre_check(code)
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# TestApiWhitelist
# ---------------------------------------------------------------------------


class TestApiWhitelist:
    def test_whitelist_contains_core_apis(self) -> None:
        """Whitelist contains essential CadQuery APIs."""
        assert "Workplane" in CADQUERY_WHITELIST
        assert "exporters.export" in CADQUERY_WHITELIST
        assert "importers.importStep" in CADQUERY_WHITELIST

    def test_whitelist_prompt_injection(self) -> None:
        """Prompt section contains header and key API names."""
        section = get_whitelist_prompt_section()
        assert "## CadQuery API 使用规范" in section
        assert "Workplane" in section

    def test_blocked_apis_listed(self) -> None:
        """Blocked APIs include show_object and addAnnotation."""
        assert "show_object" in BLOCKED_APIS
        assert "addAnnotation" in BLOCKED_APIS
