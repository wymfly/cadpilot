"""Integration tests for Phase 2 pipeline config flags and module imports."""

from __future__ import annotations

import pytest

from backend.models.pipeline_config import PipelineConfig, PRESETS


class TestPhase2ConfigFlags:
    def test_balanced_preset_enables_phase2_features(self) -> None:
        config = PRESETS["balanced"]
        assert config.best_of_n == 3
        assert config.api_whitelist is True
        assert config.ast_pre_check is True
        assert config.multi_view_render is True
        assert config.structured_feedback is True
        assert config.rollback_on_degrade is True
        assert config.topology_check is True

    def test_fast_preset_disables_expensive_features(self) -> None:
        config = PRESETS["fast"]
        assert config.best_of_n == 1
        assert config.multi_view_render is False
        assert config.topology_check is False

    def test_precise_preset_enables_all(self) -> None:
        config = PRESETS["precise"]
        assert config.best_of_n == 5
        assert config.cross_section_check is True
        assert config.multi_view_render is True

    def test_custom_config(self) -> None:
        config = PipelineConfig(preset="custom", best_of_n=2, rollback_on_degrade=False)
        assert config.best_of_n == 2
        assert config.rollback_on_degrade is False


class TestPhase2ModulesImport:
    def test_ast_checker_import(self) -> None:
        from backend.core.ast_checker import ast_pre_check, AstCheckResult

        assert callable(ast_pre_check)

    def test_api_whitelist_import(self) -> None:
        from backend.core.api_whitelist import CADQUERY_WHITELIST, get_whitelist_prompt_section

        assert len(CADQUERY_WHITELIST) > 0

    def test_candidate_scorer_import(self) -> None:
        from backend.core.candidate_scorer import score_candidate, select_best

        assert callable(score_candidate)

    def test_rollback_import(self) -> None:
        from backend.core.rollback import RollbackTracker

        tracker = RollbackTracker()
        assert tracker.rollback_count == 0

    def test_vl_feedback_import(self) -> None:
        from backend.core.vl_feedback import parse_vl_feedback, VLFeedback

        assert callable(parse_vl_feedback)

    def test_topology_import(self) -> None:
        from backend.core.validators import count_topology, compare_topology, TopologyResult

        assert callable(count_topology)
        assert callable(compare_topology)

    def test_cross_section_import(self) -> None:
        from backend.core.validators import cross_section_analysis, CrossSectionAnalysis

        assert callable(cross_section_analysis)

    def test_multi_view_render_import(self) -> None:
        from backend.infra.render import render_multi_view, STANDARD_VIEWS

        assert callable(render_multi_view)
        assert len(STANDARD_VIEWS) == 4


class TestPipelineAcceptsConfig:
    """Test that generate_step_v2 accepts a config parameter."""

    def test_generate_step_v2_signature_accepts_config(self) -> None:
        """generate_step_v2 should accept config parameter."""
        import inspect
        from backend.pipeline.pipeline import generate_step_v2

        sig = inspect.signature(generate_step_v2)
        assert "config" in sig.parameters
        param = sig.parameters["config"]
        assert param.default is None

    def test_default_config_is_balanced(self) -> None:
        """When config=None, pipeline should use balanced preset internally."""
        # This tests the import + signature, not execution
        from backend.pipeline.pipeline import generate_step_v2

        assert callable(generate_step_v2)


class TestSmartRefinerAcceptsPhase2Params:
    """Test that SmartRefiner.refine() accepts Phase 2 parameters."""

    def test_refine_accepts_structured_feedback(self) -> None:
        import inspect
        from backend.core.smart_refiner import SmartRefiner

        sig = inspect.signature(SmartRefiner.refine)
        assert "structured_feedback" in sig.parameters

    def test_structured_compare_prompt_exists(self) -> None:
        from backend.core.smart_refiner import _STRUCTURED_COMPARE_PROMPT

        assert "verdict" in _STRUCTURED_COMPARE_PROMPT
        assert "JSON" in _STRUCTURED_COMPARE_PROMPT

    def test_refine_accepts_topology_check(self) -> None:
        import inspect
        from backend.core.smart_refiner import SmartRefiner

        sig = inspect.signature(SmartRefiner.refine)
        assert "topology_check" in sig.parameters
