"""Tests for the structured Feature model (Phase 3 Task 3.1).

Validates:
- Typed feature creation (HolePatternSpec, FilletSpec, ChamferSpec, KeywaySpec, SlotSpec)
- Generic/dict fallback features
- DrawingSpec with typed features
- Backward compatibility (plain dicts auto-convert via model_validator)
- JSON round-trip serialization
- to_prompt_text() with structured features
- _extract_features_from_spec() with typed Feature objects
"""

from __future__ import annotations

import json

import pytest

from cad3dify.knowledge.part_types import (
    BaseBodySpec,
    BoreSpec,
    ChamferSpec,
    DimensionLayer,
    DrawingSpec,
    Feature,
    FilletSpec,
    HolePatternSpec,
    KeywaySpec,
    PartType,
    SlotSpec,
)


# ---------------------------------------------------------------------------
# 1. Typed Feature creation
# ---------------------------------------------------------------------------


class TestTypedFeatureCreation:
    def test_hole_pattern_feature(self) -> None:
        feat = Feature(
            type="hole_pattern",
            spec=HolePatternSpec(count=6, diameter=10, pcd=70),
        )
        assert feat.type == "hole_pattern"
        assert isinstance(feat.spec, HolePatternSpec)
        assert feat.spec.count == 6
        assert feat.spec.diameter == 10
        assert feat.spec.pcd == 70

    def test_fillet_feature(self) -> None:
        feat = Feature(
            type="fillet",
            spec=FilletSpec(radius=3, locations=["top_edge"]),
        )
        assert feat.type == "fillet"
        assert isinstance(feat.spec, FilletSpec)
        assert feat.spec.radius == 3
        assert feat.spec.locations == ["top_edge"]

    def test_chamfer_feature(self) -> None:
        feat = Feature(
            type="chamfer",
            spec=ChamferSpec(size=2, locations=["bottom"]),
        )
        assert feat.type == "chamfer"
        assert isinstance(feat.spec, ChamferSpec)
        assert feat.spec.size == 2

    def test_keyway_feature(self) -> None:
        feat = Feature(
            type="keyway",
            spec=KeywaySpec(width=5, depth=2.5, length=20),
        )
        assert feat.type == "keyway"
        assert isinstance(feat.spec, KeywaySpec)
        assert feat.spec.width == 5
        assert feat.spec.depth == 2.5
        assert feat.spec.length == 20

    def test_slot_feature(self) -> None:
        feat = Feature(
            type="slot",
            spec=SlotSpec(width=8, depth=4),
        )
        assert feat.type == "slot"
        assert isinstance(feat.spec, SlotSpec)
        assert feat.spec.width == 8
        assert feat.spec.length is None

    def test_slot_feature_with_length(self) -> None:
        feat = Feature(
            type="slot",
            spec=SlotSpec(width=8, depth=4, length=30),
        )
        assert feat.spec.length == 30


# ---------------------------------------------------------------------------
# 2. Generic / dict fallback
# ---------------------------------------------------------------------------


class TestDictFallbackFeature:
    def test_dict_spec_feature(self) -> None:
        feat = Feature(type="gear_teeth", spec={"module": 2, "teeth": 24})
        assert feat.type == "gear_teeth"
        assert isinstance(feat.spec, dict)
        assert feat.spec["module"] == 2
        assert feat.spec["teeth"] == 24

    def test_empty_spec_feature(self) -> None:
        feat = Feature(type="gear_teeth")
        assert feat.type == "gear_teeth"
        assert feat.spec == {}

    def test_unknown_type_with_dict(self) -> None:
        feat = Feature(type="custom_groove", spec={"width": 5, "angle": 45})
        assert feat.type == "custom_groove"
        assert isinstance(feat.spec, dict)


# ---------------------------------------------------------------------------
# 3. DrawingSpec with typed features
# ---------------------------------------------------------------------------


class TestDrawingSpecWithFeatures:
    def test_drawing_spec_accepts_feature_list(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL_STEPPED,
            description="法兰盘",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                Feature(type="hole_pattern", spec=HolePatternSpec(count=6, diameter=10, pcd=70)),
                Feature(type="fillet", spec=FilletSpec(radius=3)),
            ],
        )
        assert len(spec.features) == 2
        assert spec.features[0].type == "hole_pattern"
        assert isinstance(spec.features[0].spec, HolePatternSpec)

    def test_drawing_spec_mixed_features(self) -> None:
        """Typed and dict-fallback features can coexist."""
        spec = DrawingSpec(
            part_type=PartType.GEAR,
            description="直齿轮",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                Feature(type="keyway", spec=KeywaySpec(width=5, depth=2.5, length=20)),
                Feature(type="gear_teeth", spec={"module": 2, "teeth": 24}),
            ],
        )
        assert len(spec.features) == 2
        assert isinstance(spec.features[0].spec, KeywaySpec)
        assert isinstance(spec.features[1].spec, dict)


# ---------------------------------------------------------------------------
# 4. Backward compatibility — plain dicts auto-convert
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_plain_dict_auto_converts(self) -> None:
        """Plain dict like {"type": "fillet", "radius": 3} auto-converts to Feature.

        When the dict matches a known spec (e.g. FilletSpec), Pydantic's Union
        validation automatically promotes it to the typed spec.
        """
        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL,
            description="轴",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                {"type": "fillet", "radius": 3},
            ],
        )
        assert len(spec.features) == 1
        feat = spec.features[0]
        assert isinstance(feat, Feature)
        assert feat.type == "fillet"
        # Pydantic Union matches {"radius": 3} to FilletSpec automatically
        assert isinstance(feat.spec, FilletSpec)
        assert feat.spec.radius == 3

    def test_plain_dict_hole_pattern(self) -> None:
        """Hole pattern dict auto-converts to typed HolePatternSpec."""
        spec = DrawingSpec(
            part_type=PartType.PLATE,
            description="安装板",
            base_body=BaseBodySpec(method="extrude"),
            features=[
                {"type": "hole_pattern", "count": 4, "diameter": 12, "pcd": 80},
            ],
        )
        feat = spec.features[0]
        assert feat.type == "hole_pattern"
        assert isinstance(feat.spec, HolePatternSpec)
        assert feat.spec.count == 4
        assert feat.spec.diameter == 12

    def test_multiple_plain_dicts(self) -> None:
        """Multiple plain dicts auto-convert."""
        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL_STEPPED,
            description="法兰盘",
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
        assert len(spec.features) == 2
        assert all(isinstance(f, Feature) for f in spec.features)
        assert spec.features[0].type == "hole_pattern"
        assert spec.features[1].type == "fillet"

    def test_empty_dict_auto_converts(self) -> None:
        """Dict with only type auto-converts."""
        spec = DrawingSpec(
            part_type=PartType.GEAR,
            description="齿轮",
            base_body=BaseBodySpec(method="revolve"),
            features=[{"type": "gear_teeth"}, {"type": "keyway"}],
        )
        assert spec.features[0].type == "gear_teeth"
        assert spec.features[1].type == "keyway"

    def test_dict_without_type_gets_unknown(self) -> None:
        """Dict without 'type' key gets type='unknown'.

        Note: {"radius": 5} matches FilletSpec, so Pydantic auto-promotes it.
        """
        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="test",
            base_body=BaseBodySpec(method="extrude"),
            features=[{"radius": 5}],
        )
        assert spec.features[0].type == "unknown"
        # Pydantic matches {"radius": 5} to FilletSpec automatically
        assert isinstance(spec.features[0].spec, FilletSpec)
        assert spec.features[0].spec.radius == 5

    def test_truly_unknown_dict_stays_dict(self) -> None:
        """Dict that doesn't match any known spec stays as dict."""
        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="test",
            base_body=BaseBodySpec(method="extrude"),
            features=[{"type": "custom_feature", "angle": 45, "offset": 10}],
        )
        assert spec.features[0].type == "custom_feature"
        assert isinstance(spec.features[0].spec, dict)
        assert spec.features[0].spec["angle"] == 45


# ---------------------------------------------------------------------------
# 5. JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_feature_round_trip(self) -> None:
        feat = Feature(
            type="hole_pattern",
            spec=HolePatternSpec(count=6, diameter=10, pcd=70),
        )
        data = feat.model_dump()
        restored = Feature.model_validate(data)
        assert restored.type == "hole_pattern"
        # After round-trip through dict, spec becomes dict (no discriminated union)
        # This is expected behavior — the important thing is data preservation
        if isinstance(restored.spec, dict):
            assert restored.spec["count"] == 6
        else:
            assert restored.spec.count == 6

    def test_drawing_spec_json_round_trip(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL,
            description="轴",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                {"type": "fillet", "radius": 3},
                {"type": "hole_pattern", "count": 4, "diameter": 8},
            ],
        )
        json_str = spec.model_dump_json()
        restored = DrawingSpec.model_validate_json(json_str)
        assert len(restored.features) == 2
        assert restored.features[0].type == "fillet"
        assert restored.features[1].type == "hole_pattern"

    def test_full_json_serialization(self) -> None:
        """Ensure JSON serialization produces valid JSON."""
        feat = Feature(type="keyway", spec=KeywaySpec(width=5, depth=2.5, length=20))
        json_str = feat.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["type"] == "keyway"
        assert "spec" in parsed


# ---------------------------------------------------------------------------
# 6. to_prompt_text with features
# ---------------------------------------------------------------------------


class TestToPromptText:
    def test_prompt_text_with_typed_features(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL_STEPPED,
            description="法兰盘",
            views=["front_section"],
            overall_dimensions={"max_diameter": 100},
            base_body=BaseBodySpec(method="revolve"),
            features=[
                Feature(type="hole_pattern", spec=HolePatternSpec(count=6, diameter=10, pcd=70)),
                Feature(type="fillet", spec=FilletSpec(radius=3)),
            ],
        )
        text = spec.to_prompt_text()
        assert "## 特征" in text
        assert "hole_pattern" in text
        assert "fillet" in text

    def test_prompt_text_with_dict_features(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.GEAR,
            description="齿轮",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                {"type": "gear_teeth", "module": 2, "teeth": 24},
            ],
        )
        text = spec.to_prompt_text()
        assert "## 特征" in text
        assert "gear_teeth" in text

    def test_prompt_text_no_features(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="simple block",
            base_body=BaseBodySpec(method="extrude"),
        )
        text = spec.to_prompt_text()
        assert "## 特征" not in text


# ---------------------------------------------------------------------------
# 7. _extract_features_from_spec with typed Feature
# ---------------------------------------------------------------------------


class TestExtractFeaturesWithTypedFeature:
    def test_extracts_typed_feature_types(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = DrawingSpec(
            part_type=PartType.ROTATIONAL_STEPPED,
            description="法兰盘",
            base_body=BaseBodySpec(
                method="revolve",
                bore=BoreSpec(diameter=10, through=True),
            ),
            features=[
                Feature(type="hole_pattern", spec=HolePatternSpec(count=6, diameter=10, pcd=70)),
                Feature(type="fillet", spec=FilletSpec(radius=3)),
            ],
        )
        features = _extract_features_from_spec(spec)
        assert "revolve" in features
        assert "bore" in features
        assert "hole_pattern" in features
        assert "fillet" in features

    def test_extracts_dict_fallback_feature_types(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = DrawingSpec(
            part_type=PartType.GEAR,
            description="齿轮",
            base_body=BaseBodySpec(method="revolve"),
            features=[
                {"type": "gear_teeth"},
                {"type": "keyway"},
            ],
        )
        features = _extract_features_from_spec(spec)
        assert "gear_teeth" in features
        assert "keyway" in features

    def test_extracts_mixed_features(self) -> None:
        from cad3dify.v2.modeling_strategist import _extract_features_from_spec

        spec = DrawingSpec(
            part_type=PartType.BRACKET,
            description="支架",
            base_body=BaseBodySpec(method="extrude"),
            features=[
                Feature(type="chamfer", spec=ChamferSpec(size=2)),
                {"type": "slot", "width": 10},
            ],
        )
        features = _extract_features_from_spec(spec)
        assert "chamfer" in features
        assert "slot" in features
        assert "extrude" in features
