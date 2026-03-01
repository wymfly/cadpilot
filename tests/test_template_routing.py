"""Tests for part_type-based template routing in analyze_intent_node."""
import pytest
from unittest.mock import patch, MagicMock


class TestTemplateRouting:
    def test_part_type_routes_to_matching_templates(self):
        from backend.core.spec_compiler import rank_templates
        tpl = MagicMock()
        tpl.name = "cylinder_simple"
        tpl.params = [MagicMock(name="diameter"), MagicMock(name="height")]
        tpl.part_type = "rotational"
        result = rank_templates([tpl], {"diameter": 50, "height": 100})
        assert result[0].name == "cylinder_simple"

    def test_no_match_returns_none(self):
        from backend.core.spec_compiler import rank_templates
        assert rank_templates([], {"diameter": 50}) == []

    def test_ranking_prefers_higher_coverage(self):
        from backend.core.spec_compiler import rank_templates
        t1 = MagicMock()
        t1.name = "full_match"
        t1.params = [MagicMock(name="diameter"), MagicMock(name="height")]
        t2 = MagicMock()
        t2.name = "partial_match"
        t2.params = [MagicMock(name="diameter"), MagicMock(name="height"), MagicMock(name="wall")]
        ranked = rank_templates([t1, t2], {"diameter": 50, "height": 100})
        assert ranked[0].name == "full_match"


class TestEngineeringStandardsIntegration:
    def test_recommend_params_rotational(self):
        from backend.core.engineering_standards import EngineeringStandards
        standards = EngineeringStandards()
        recs = standards.recommend_params("rotational", {"diameter": 50})
        assert isinstance(recs, list)
        for r in recs:
            assert hasattr(r, "param_name")
            assert hasattr(r, "value")

    def test_recommend_params_unknown_type(self):
        from backend.core.engineering_standards import EngineeringStandards
        standards = EngineeringStandards()
        recs = standards.recommend_params("unknown_type", {"x": 1})
        assert recs == []
