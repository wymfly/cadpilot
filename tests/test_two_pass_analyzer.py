"""Tests for two-pass drawing analysis."""
import pytest

from backend.core.two_pass_analyzer import (
    TwoPassAnalyzer,
    Pass1Result,
    Pass2Result,
)
from backend.knowledge.part_types import DrawingSpec, PartType


class TestPass1Result:
    def test_basic_fields(self):
        r = Pass1Result(
            part_type=PartType.ROTATIONAL_STEPPED,
            step_count=3,
            feature_count=2,
            views=["front_section", "top"],
        )
        assert r.part_type == PartType.ROTATIONAL_STEPPED
        assert r.step_count == 3
        assert r.feature_count == 2
        assert r.views == ["front_section", "top"]

    def test_rotational_type(self):
        r = Pass1Result(
            part_type=PartType.ROTATIONAL,
            step_count=1,
            feature_count=0,
            views=["front"],
        )
        assert r.part_type == PartType.ROTATIONAL

    def test_plate_type(self):
        r = Pass1Result(
            part_type=PartType.PLATE,
            step_count=0,
            feature_count=3,
            views=["front", "top", "side"],
        )
        assert r.part_type == PartType.PLATE
        assert r.step_count == 0

    def test_empty_views(self):
        r = Pass1Result(
            part_type=PartType.GENERAL,
            step_count=0,
            feature_count=0,
            views=[],
        )
        assert r.views == []


class TestPass2Result:
    def test_basic_fields(self):
        r = Pass2Result(
            dimensions={"diameter": 100.0, "height": 30.0},
            features=[{"type": "hole_pattern", "count": 6, "diameter": 10}],
        )
        assert r.dimensions["diameter"] == 100.0
        assert len(r.features) == 1
        assert r.features[0]["type"] == "hole_pattern"

    def test_empty_features(self):
        r = Pass2Result(
            dimensions={"diameter": 50.0},
            features=[],
        )
        assert r.features == []
        assert r.dimensions["diameter"] == 50.0

    def test_multiple_features(self):
        r = Pass2Result(
            dimensions={"width": 200.0, "length": 150.0, "height": 10.0},
            features=[
                {"type": "hole_pattern", "count": 4, "diameter": 8},
                {"type": "fillet", "radius": 3},
                {"type": "chamfer", "size": 1},
            ],
        )
        assert len(r.features) == 3

    def test_empty_dimensions(self):
        r = Pass2Result(dimensions={}, features=[])
        assert r.dimensions == {}


class TestTwoPassAnalyzer:
    def test_init_with_mock_llm(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.ROTATIONAL,
                step_count=1,
                feature_count=0,
                views=["front"],
            )

        async def mock_pass2(image: bytes, pass1_result: Pass1Result) -> Pass2Result:
            return Pass2Result(
                dimensions={"diameter": 50.0},
                features=[],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        assert analyzer is not None

    @pytest.mark.asyncio
    async def test_analyze_two_pass(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.ROTATIONAL_STEPPED,
                step_count=2,
                feature_count=1,
                views=["front_section"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(
                dimensions={"max_diameter": 100.0, "total_height": 30.0},
                features=[{"type": "hole_pattern", "count": 4}],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert spec.part_type == PartType.ROTATIONAL_STEPPED
        assert spec.overall_dimensions["max_diameter"] == 100.0
        assert spec.overall_dimensions["total_height"] == 30.0
        assert len(spec.features) == 1

    @pytest.mark.asyncio
    async def test_analyze_rotational_uses_revolve(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.ROTATIONAL,
                step_count=1,
                feature_count=0,
                views=["front"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(
                dimensions={"diameter": 50.0},
                features=[],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert spec.base_body.method == "revolve"

    @pytest.mark.asyncio
    async def test_analyze_plate_uses_extrude(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.PLATE,
                step_count=0,
                feature_count=2,
                views=["front", "top"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(
                dimensions={"width": 200.0, "length": 150.0, "height": 10.0},
                features=[{"type": "hole_pattern", "count": 4, "diameter": 8}],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert spec.base_body.method == "extrude"
        assert spec.part_type == PartType.PLATE

    @pytest.mark.asyncio
    async def test_pass1_failure_returns_none(self):
        async def mock_pass1(image: bytes) -> None:
            return None

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(dimensions={}, features=[])

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        result = await analyzer.analyze(b"fake_image")
        assert result is None

    @pytest.mark.asyncio
    async def test_pass2_receives_pass1_result(self):
        """Verify that pass2_fn receives the correct Pass1Result from pass1_fn."""
        received_pass1: list[Pass1Result] = []

        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.BRACKET,
                step_count=0,
                feature_count=5,
                views=["front", "side", "isometric"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            received_pass1.append(pass1_result)
            return Pass2Result(
                dimensions={"width": 80.0},
                features=[],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert len(received_pass1) == 1
        assert received_pass1[0].part_type == PartType.BRACKET
        assert received_pass1[0].feature_count == 5

    @pytest.mark.asyncio
    async def test_description_includes_part_type(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.GEAR,
                step_count=0,
                feature_count=1,
                views=["front"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(
                dimensions={"diameter": 80.0},
                features=[],
            )

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert "gear" in spec.description

    @pytest.mark.asyncio
    async def test_views_propagated(self):
        async def mock_pass1(image: bytes) -> Pass1Result:
            return Pass1Result(
                part_type=PartType.HOUSING,
                step_count=0,
                feature_count=0,
                views=["front", "top", "section"],
            )

        async def mock_pass2(
            image: bytes, pass1_result: Pass1Result
        ) -> Pass2Result:
            return Pass2Result(dimensions={}, features=[])

        analyzer = TwoPassAnalyzer(pass1_fn=mock_pass1, pass2_fn=mock_pass2)
        spec = await analyzer.analyze(b"fake_image")
        assert spec is not None
        assert spec.views == ["front", "top", "section"]
