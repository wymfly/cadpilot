"""Tests for SpecCompiler — unified code compilation dispatch."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.core.spec_compiler import SpecCompiler, CompileResult, CompilationError


def _make_param(param_name: str) -> MagicMock:
    """Create a mock param with .name set as attribute (not constructor arg)."""
    p = MagicMock()
    p.name = param_name
    return p


class TestCompileResult:
    def test_template_result(self):
        r = CompileResult(
            method="template",
            template_name="cylinder_simple",
            step_path="/tmp/model.step",
        )
        assert r.method == "template"
        assert r.template_name == "cylinder_simple"

    def test_llm_result(self):
        r = CompileResult(method="llm_fallback", step_path="/tmp/model.step")
        assert r.method == "llm_fallback"
        assert r.template_name is None


class TestSpecCompilerInit:
    def test_creates_instance(self):
        compiler = SpecCompiler()
        assert compiler is not None


class TestCompileFromTemplate:
    @patch("backend.infra.sandbox.SafeExecutor")
    @patch("backend.core.template_engine.TemplateEngine.from_directory")
    def test_template_success(self, mock_from_dir, MockExecutor):
        engine = mock_from_dir.return_value
        engine.render.return_value = "import cadquery as cq; cq.Workplane('XY').box(10,10,10)"
        executor_inst = MockExecutor.return_value
        executor_inst.execute.return_value = MagicMock(success=True, stderr="")

        compiler = SpecCompiler()
        with patch.object(Path, "exists", return_value=True):
            result = compiler.compile(
                matched_template="cylinder_simple",
                params={"diameter": 50},
                output_path="/tmp/model.step",
            )

        assert result.method == "template"
        assert result.template_name == "cylinder_simple"
        engine.render.assert_called_once()

    @patch("backend.infra.sandbox.SafeExecutor")
    @patch("backend.core.template_engine.TemplateEngine.from_directory")
    def test_template_fail_falls_back_to_llm(self, mock_from_dir, MockExecutor):
        mock_from_dir.return_value.render.side_effect = RuntimeError("Template render error")

        compiler = SpecCompiler()
        # LLM fallback will also fail in test (no real pipeline)
        with pytest.raises(CompilationError, match="Both template and LLM"):
            compiler.compile(
                matched_template="bad_template",
                params={},
                output_path="/tmp/model.step",
            )

    def test_no_template_goes_to_llm(self):
        compiler = SpecCompiler()
        # Without mocking LLM, this should raise CompilationError
        with pytest.raises((CompilationError, Exception)):
            compiler.compile(
                matched_template=None,
                params={},
                output_path="/tmp/model.step",
            )


class TestRankTemplates:
    def test_higher_coverage_wins(self):
        """Template with more matching params should rank first."""
        from backend.core.spec_compiler import rank_templates

        t1 = MagicMock()
        t1.name = "simple"
        t1.params = [_make_param("diameter"), _make_param("height")]

        t2 = MagicMock()
        t2.name = "complex"
        t2.params = [
            _make_param("diameter"),
            _make_param("height"),
            _make_param("wall_thickness"),
            _make_param("fillet_radius"),
        ]

        known_params = {"diameter": 50, "height": 100}
        ranked = rank_templates([t1, t2], known_params)
        # t1 has 2/2 coverage (1.0), t2 has 2/4 coverage (0.5)
        assert ranked[0].name == "simple"

    def test_empty_candidates_returns_empty(self):
        from backend.core.spec_compiler import rank_templates

        assert rank_templates([], {"x": 1}) == []

    def test_same_score_fewer_params_wins(self):
        from backend.core.spec_compiler import rank_templates

        t1 = MagicMock()
        t1.name = "a"
        t1.params = [_make_param("d"), _make_param("h"), _make_param("extra")]
        t2 = MagicMock()
        t2.name = "b"
        t2.params = [_make_param("d"), _make_param("h")]
        ranked = rank_templates([t1, t2], {"d": 1, "h": 2})
        assert ranked[0].name == "b"  # fewer params -> simpler
