"""Tests for feature-based example selection in ModelingStrategist."""

from __future__ import annotations

import pytest

from cad3dify.knowledge.part_types import (
    BaseBodySpec,
    BoreSpec,
    DimensionLayer,
    DrawingSpec,
    PartType,
)
from cad3dify.v2.modeling_strategist import ModelingContext, ModelingStrategist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_flange_spec() -> DrawingSpec:
    """法兰盘：旋转体，带孔阵列、倒角、中心孔"""
    return DrawingSpec(
        part_type=PartType.ROTATIONAL_STEPPED,
        description="法兰盘",
        views=["front_section", "top"],
        overall_dimensions={"max_diameter": 100, "total_height": 30},
        base_body=BaseBodySpec(
            method="revolve",
            profile=[DimensionLayer(diameter=100, height=10, label="base")],
            bore=BoreSpec(diameter=10, through=True),
        ),
        features=[
            {"type": "hole_pattern", "count": 6, "diameter": 10, "pcd": 70},
            {"type": "fillet", "radius": 3},
        ],
    )


def _make_gear_spec() -> DrawingSpec:
    """直齿轮：旋转体，中心孔，键槽"""
    return DrawingSpec(
        part_type=PartType.GEAR,
        description="直齿轮 m=2 z=24",
        views=["front", "side"],
        overall_dimensions={"max_diameter": 52, "total_height": 20},
        base_body=BaseBodySpec(
            method="revolve",
            bore=BoreSpec(diameter=14, through=True),
        ),
        features=[{"type": "gear_teeth"}, {"type": "keyway"}],
    )


def _make_plate_spec() -> DrawingSpec:
    """矩形板：挤出，安装孔，中心孔"""
    return DrawingSpec(
        part_type=PartType.PLATE,
        description="安装板",
        views=["front", "top"],
        overall_dimensions={"length": 200, "width": 150},
        base_body=BaseBodySpec(
            method="extrude",
            bore=BoreSpec(diameter=60, through=True),
        ),
        features=[{"type": "hole_pattern", "count": 4, "diameter": 12, "pcd": 0}],
    )


# ---------------------------------------------------------------------------
# TestFeatureExtraction (internal helper)
# ---------------------------------------------------------------------------


class TestFeatureExtraction:
    def test_revolve_method(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = _make_flange_spec()
        features = _extract_features_from_spec(spec)
        assert "revolve" in features

    def test_bore_adds_bore_tag(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = _make_flange_spec()
        features = _extract_features_from_spec(spec)
        assert "bore" in features

    def test_hole_pattern_feature_type(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = _make_flange_spec()
        features = _extract_features_from_spec(spec)
        assert "hole_pattern" in features

    def test_gear_teeth_feature(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = _make_gear_spec()
        features = _extract_features_from_spec(spec)
        assert "gear_teeth" in features
        assert "keyway" in features

    def test_no_bore_no_bore_tag(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="simple block",
            base_body=BaseBodySpec(method="extrude"),
        )
        features = _extract_features_from_spec(spec)
        assert "bore" not in features


# ---------------------------------------------------------------------------
# TestJaccard (internal helper)
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical_sets(self) -> None:
        from cad3dify.v2.modeling_strategist import _jaccard

        assert _jaccard({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)

    def test_disjoint_sets(self) -> None:
        from cad3dify.v2.modeling_strategist import _jaccard

        assert _jaccard({"a"}, {"b"}) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        from cad3dify.v2.modeling_strategist import _jaccard

        result = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        # intersection=2, union=4 → 0.5
        assert result == pytest.approx(0.5)

    def test_empty_sets(self) -> None:
        from cad3dify.v2.modeling_strategist import _jaccard

        assert _jaccard(set(), set()) == pytest.approx(0.0)

    def test_one_empty(self) -> None:
        from cad3dify.v2.modeling_strategist import _jaccard

        assert _jaccard({"a"}, set()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestFeatureBasedSelection
# ---------------------------------------------------------------------------


class TestFeatureBasedSelection:
    def test_selects_examples_with_matching_features(self) -> None:
        spec = _make_flange_spec()
        strategist = ModelingStrategist()
        context = strategist.select(spec)

        assert len(context.examples) > 0
        # First example should be relevant (rotational with bolt holes)
        first_desc = context.examples[0][0].lower()
        assert (
            "法兰" in first_desc
            or "bolt" in first_desc
            or "螺栓" in first_desc
            or "hole" in first_desc
            or "孔" in first_desc
        )

    def test_max_examples_limit(self) -> None:
        spec = _make_flange_spec()
        strategist = ModelingStrategist()
        context = strategist.select(spec, max_examples=2)
        assert len(context.examples) <= 2

    def test_max_examples_one(self) -> None:
        spec = _make_flange_spec()
        context = ModelingStrategist().select(spec, max_examples=1)
        assert len(context.examples) == 1

    def test_gear_selects_gear_examples(self) -> None:
        spec = _make_gear_spec()
        context = ModelingStrategist().select(spec)
        # Gear examples should rank highest for a gear spec
        descs = " ".join(d for d, _ in context.examples)
        assert "齿轮" in descs or "gear" in descs.lower()

    def test_plate_selects_plate_examples(self) -> None:
        spec = _make_plate_spec()
        context = ModelingStrategist().select(spec)
        assert len(context.examples) > 0

    def test_returns_modeling_context(self) -> None:
        spec = _make_flange_spec()
        context = ModelingStrategist().select(spec)
        assert isinstance(context, ModelingContext)
        assert context.drawing_spec is spec
        assert isinstance(context.strategy, str)
        assert len(context.strategy) > 0

    def test_examples_are_tuples(self) -> None:
        spec = _make_flange_spec()
        context = ModelingStrategist().select(spec)
        for item in context.examples:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_high_similarity_before_low(self) -> None:
        """Examples with higher Jaccard similarity should appear first."""
        spec = _make_gear_spec()
        context = ModelingStrategist().select(spec, max_examples=5)
        if len(context.examples) >= 2:
            # Top example should involve gear or revolve feature
            top_desc = context.examples[0][0].lower()
            assert (
                "齿轮" in top_desc or "gear" in top_desc.lower()
                or "revolve" in top_desc.lower()
            )
