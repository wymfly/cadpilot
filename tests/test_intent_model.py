"""Tests for IntentSpec, ParamRecommendation, PreciseSpec and intent_to_precise()."""

from __future__ import annotations

import json

import pytest

from backend.knowledge.part_types import (
    BaseBodySpec,
    DrawingSpec,
    PartType,
)
from backend.models.intent import (
    IntentSpec,
    ParamRecommendation,
    PreciseSpec,
    intent_to_precise,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def flange_intent() -> IntentSpec:
    return IntentSpec(
        part_category="法兰盘",
        part_type=PartType.ROTATIONAL,
        known_params={"outer_diameter": 100.0, "thickness": 16.0},
        missing_params=["pcd", "hole_count", "hole_diameter"],
        constraints=["需要和M10螺栓配合"],
        confidence=0.85,
        raw_text="做一个法兰盘，外径100mm，厚16mm，6个M10螺栓孔",
    )


@pytest.fixture()
def minimal_intent() -> IntentSpec:
    return IntentSpec(raw_text="做一个零件")


@pytest.fixture()
def sample_recommendation() -> ParamRecommendation:
    return ParamRecommendation(
        param_name="pcd",
        value=75.0,
        unit="mm",
        reason="GB/T 9119 法兰标准推荐值",
        source="GB/T 9119",
    )


# ===================================================================
# IntentSpec -- basic construction
# ===================================================================


class TestIntentSpecBasic:
    def test_create_with_all_fields(self, flange_intent: IntentSpec) -> None:
        assert flange_intent.part_category == "法兰盘"
        assert flange_intent.part_type == PartType.ROTATIONAL
        assert flange_intent.known_params["outer_diameter"] == 100.0
        assert "pcd" in flange_intent.missing_params
        assert len(flange_intent.constraints) == 1
        assert flange_intent.confidence == 0.85
        assert flange_intent.raw_text != ""

    def test_create_minimal(self, minimal_intent: IntentSpec) -> None:
        assert minimal_intent.part_category == ""
        assert minimal_intent.part_type is None
        assert minimal_intent.known_params == {}
        assert minimal_intent.missing_params == []
        assert minimal_intent.constraints == []
        assert minimal_intent.reference_image is None
        assert minimal_intent.confidence == 0.0

    def test_reference_image(self) -> None:
        intent = IntentSpec(
            raw_text="参考这张图",
            reference_image="/tmp/ref.png",
        )
        assert intent.reference_image == "/tmp/ref.png"


# ===================================================================
# IntentSpec -- serialization round-trip
# ===================================================================


class TestIntentSpecSerialization:
    def test_json_round_trip(self, flange_intent: IntentSpec) -> None:
        json_str = flange_intent.model_dump_json()
        restored = IntentSpec.model_validate_json(json_str)
        assert restored == flange_intent

    def test_dict_round_trip(self, flange_intent: IntentSpec) -> None:
        data = flange_intent.model_dump()
        restored = IntentSpec.model_validate(data)
        assert restored == flange_intent

    def test_json_preserves_part_type_enum(
        self, flange_intent: IntentSpec
    ) -> None:
        data = json.loads(flange_intent.model_dump_json())
        assert data["part_type"] == "rotational"
        restored = IntentSpec.model_validate(data)
        assert restored.part_type == PartType.ROTATIONAL

    def test_json_none_part_type(self, minimal_intent: IntentSpec) -> None:
        data = json.loads(minimal_intent.model_dump_json())
        assert data["part_type"] is None
        restored = IntentSpec.model_validate(data)
        assert restored.part_type is None


# ===================================================================
# IntentSpec -- boundary / validation
# ===================================================================


class TestIntentSpecBoundary:
    def test_confidence_zero(self) -> None:
        intent = IntentSpec(confidence=0.0, raw_text="")
        assert intent.confidence == 0.0

    def test_confidence_one(self) -> None:
        intent = IntentSpec(confidence=1.0, raw_text="")
        assert intent.confidence == 1.0

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(Exception):
            IntentSpec(confidence=1.5, raw_text="")

    def test_confidence_negative_raises(self) -> None:
        with pytest.raises(Exception):
            IntentSpec(confidence=-0.1, raw_text="")

    def test_empty_known_params(self) -> None:
        intent = IntentSpec(raw_text="test")
        assert intent.known_params == {}

    def test_all_part_types(self) -> None:
        for pt in PartType:
            intent = IntentSpec(part_type=pt, raw_text=pt.value)
            assert intent.part_type == pt


# ===================================================================
# ParamRecommendation
# ===================================================================


class TestParamRecommendation:
    def test_create(self, sample_recommendation: ParamRecommendation) -> None:
        assert sample_recommendation.param_name == "pcd"
        assert sample_recommendation.value == 75.0
        assert sample_recommendation.unit == "mm"
        assert sample_recommendation.source == "GB/T 9119"

    def test_default_unit(self) -> None:
        rec = ParamRecommendation(
            param_name="depth", value=10.0, reason="standard"
        )
        assert rec.unit == "mm"
        assert rec.source == ""

    def test_json_round_trip(
        self, sample_recommendation: ParamRecommendation
    ) -> None:
        json_str = sample_recommendation.model_dump_json()
        restored = ParamRecommendation.model_validate_json(json_str)
        assert restored == sample_recommendation


# ===================================================================
# PreciseSpec -- inheritance
# ===================================================================


class TestPreciseSpecInheritance:
    def test_inherits_drawing_spec_fields(self) -> None:
        spec = PreciseSpec(
            part_type=PartType.ROTATIONAL,
            description="test flange",
            overall_dimensions={"outer_diameter": 100.0},
            base_body=BaseBodySpec(method="revolve"),
            views=["front", "top"],
            notes=["M10 bolts"],
            source="text_input",
        )
        # DrawingSpec fields
        assert spec.part_type == PartType.ROTATIONAL
        assert spec.description == "test flange"
        assert spec.overall_dimensions == {"outer_diameter": 100.0}
        assert spec.base_body.method == "revolve"
        assert spec.views == ["front", "top"]
        assert spec.notes == ["M10 bolts"]
        assert spec.features == []
        # PreciseSpec fields
        assert spec.source == "text_input"
        assert spec.confirmed_by_user is True
        assert spec.intent is None
        assert spec.recommendations_applied == []

    def test_is_subclass_of_drawing_spec(self) -> None:
        assert issubclass(PreciseSpec, DrawingSpec)

    def test_instance_of_drawing_spec(self) -> None:
        spec = PreciseSpec(
            part_type=PartType.GENERAL,
            description="x",
            base_body=BaseBodySpec(method="extrude"),
        )
        assert isinstance(spec, DrawingSpec)

    def test_to_prompt_text_works(self) -> None:
        spec = PreciseSpec(
            part_type=PartType.PLATE,
            description="a plate",
            overall_dimensions={"width": 50.0},
            base_body=BaseBodySpec(method="extrude"),
        )
        text = spec.to_prompt_text()
        assert "plate" in text
        assert "50.0" in text

    def test_source_literals(self) -> None:
        for src in ("text_input", "drawing_input", "image_input"):
            spec = PreciseSpec(
                part_type=PartType.GENERAL,
                description="d",
                base_body=BaseBodySpec(method="extrude"),
                source=src,  # type: ignore[arg-type]
            )
            assert spec.source == src

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(Exception):
            PreciseSpec(
                part_type=PartType.GENERAL,
                description="d",
                base_body=BaseBodySpec(method="extrude"),
                source="invalid",  # type: ignore[arg-type]
            )


# ===================================================================
# PreciseSpec -- serialization round-trip
# ===================================================================


class TestPreciseSpecSerialization:
    def test_json_round_trip(self, flange_intent: IntentSpec) -> None:
        spec = PreciseSpec(
            part_type=PartType.ROTATIONAL,
            description="法兰盘",
            overall_dimensions={"od": 100.0, "thickness": 16.0},
            base_body=BaseBodySpec(method="revolve"),
            source="text_input",
            confirmed_by_user=True,
            intent=flange_intent,
            recommendations_applied=["pcd", "hole_count"],
        )
        json_str = spec.model_dump_json()
        restored = PreciseSpec.model_validate_json(json_str)
        assert restored == spec
        assert restored.intent == flange_intent
        assert restored.recommendations_applied == ["pcd", "hole_count"]

    def test_dict_round_trip_with_intent(
        self, flange_intent: IntentSpec
    ) -> None:
        spec = PreciseSpec(
            part_type=PartType.BRACKET,
            description="bracket",
            base_body=BaseBodySpec(method="extrude"),
            intent=flange_intent,
        )
        data = spec.model_dump()
        restored = PreciseSpec.model_validate(data)
        assert restored.intent is not None
        assert restored.intent.part_category == "法兰盘"


# ===================================================================
# intent_to_precise()
# ===================================================================


class TestIntentToPrecise:
    def test_basic_conversion(self, flange_intent: IntentSpec) -> None:
        confirmed = {"pcd": 75.0, "hole_count": 4.0}
        result = intent_to_precise(flange_intent, confirmed)
        assert isinstance(result, PreciseSpec)
        assert isinstance(result, DrawingSpec)
        assert result.part_type == PartType.ROTATIONAL
        assert result.source == "text_input"
        assert result.confirmed_by_user is True

    def test_merges_known_and_confirmed_params(
        self, flange_intent: IntentSpec
    ) -> None:
        confirmed = {"pcd": 75.0, "hole_count": 4.0}
        result = intent_to_precise(flange_intent, confirmed)
        dims = result.overall_dimensions
        # Known params from intent
        assert dims["outer_diameter"] == 100.0
        assert dims["thickness"] == 16.0
        # Confirmed params
        assert dims["pcd"] == 75.0
        assert dims["hole_count"] == 4.0

    def test_confirmed_overrides_known(self) -> None:
        intent = IntentSpec(
            part_type=PartType.ROTATIONAL,
            known_params={"outer_diameter": 100.0},
            raw_text="test",
        )
        # User corrects diameter
        result = intent_to_precise(intent, {"outer_diameter": 120.0})
        assert result.overall_dimensions["outer_diameter"] == 120.0

    def test_preserves_intent_reference(
        self, flange_intent: IntentSpec
    ) -> None:
        result = intent_to_precise(flange_intent, {})
        assert result.intent is flange_intent

    def test_recommendations_applied_tracking(self) -> None:
        intent = IntentSpec(
            part_type=PartType.PLATE,
            known_params={"width": 50.0},
            raw_text="plate",
        )
        confirmed = {"length": 100.0, "height": 10.0}
        result = intent_to_precise(intent, confirmed)
        assert "length" in result.recommendations_applied
        assert "height" in result.recommendations_applied

    def test_none_part_type_falls_back_to_general(self) -> None:
        intent = IntentSpec(
            part_type=None,
            raw_text="unknown part",
        )
        result = intent_to_precise(intent, {"width": 10.0})
        assert result.part_type == PartType.GENERAL

    def test_base_body_method_parameter(self) -> None:
        intent = IntentSpec(
            part_type=PartType.ROTATIONAL,
            raw_text="shaft",
        )
        result = intent_to_precise(intent, {}, base_body_method="revolve")
        assert result.base_body.method == "revolve"

    def test_base_body_extracts_dimensions(self) -> None:
        intent = IntentSpec(
            part_type=PartType.PLATE,
            raw_text="plate",
        )
        confirmed = {"width": 50.0, "length": 100.0, "height": 10.0}
        result = intent_to_precise(intent, confirmed)
        assert result.base_body.width == 50.0
        assert result.base_body.length == 100.0
        assert result.base_body.height == 10.0

    def test_empty_confirmed_params(self, flange_intent: IntentSpec) -> None:
        result = intent_to_precise(flange_intent, {})
        # Should still have known params
        assert result.overall_dimensions["outer_diameter"] == 100.0
        assert result.recommendations_applied == []

    def test_description_from_category(self) -> None:
        intent = IntentSpec(
            part_category="齿轮",
            part_type=PartType.GEAR,
            raw_text="齿轮",
        )
        result = intent_to_precise(intent, {})
        assert result.description == "齿轮"

    def test_description_fallback_to_part_type(self) -> None:
        intent = IntentSpec(
            part_type=PartType.BRACKET,
            raw_text="bracket",
        )
        result = intent_to_precise(intent, {})
        assert result.description == "bracket"
