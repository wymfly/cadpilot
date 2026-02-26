"""Tests for reference image understanding."""
import pytest

from backend.core.image_understanding import (
    ImageAnalyzer,
    ImageAnalysisResult,
    apply_text_modifications,
)
from backend.knowledge.part_types import PartType


class TestImageAnalysisResult:
    def test_basic_fields(self):
        r = ImageAnalysisResult(
            part_type=PartType.ROTATIONAL,
            extracted_params={"diameter": 100.0, "height": 30.0},
            description="圆柱形零件",
            confidence=0.85,
        )
        assert r.part_type == PartType.ROTATIONAL
        assert r.extracted_params["diameter"] == 100.0

    def test_optional_part_type(self):
        r = ImageAnalysisResult(
            part_type=None,
            extracted_params={},
            description="无法识别",
            confidence=0.1,
        )
        assert r.part_type is None
        assert r.confidence == 0.1


class TestApplyTextModifications:
    def test_simple_override(self):
        base = {"diameter": 100.0, "height": 30.0}
        modified = apply_text_modifications(base, "外径改为 150")
        # Should detect "外径" maps to "diameter" and update
        assert modified["diameter"] == 150.0
        assert modified["height"] == 30.0

    def test_height_modification(self):
        base = {"diameter": 100.0, "height": 30.0}
        modified = apply_text_modifications(base, "高度改为 50")
        assert modified["height"] == 50.0

    def test_no_modification(self):
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "这个零件很好")
        assert modified == base

    def test_multiple_modifications(self):
        base = {"diameter": 100.0, "height": 30.0}
        modified = apply_text_modifications(base, "外径改为 200，高度改为 60")
        assert modified["diameter"] == 200.0
        assert modified["height"] == 60.0

    def test_add_new_param(self):
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "通孔直径改为 20")
        # "通孔直径" maps to "bore_diameter", which is a new param
        assert modified.get("bore_diameter") == 20.0
        # original param unchanged
        assert modified["diameter"] == 100.0

    def test_pattern_gaicheng(self):
        """Test '改成' pattern variant."""
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "直径改成 200")
        assert modified["diameter"] == 200.0

    def test_pattern_shewei(self):
        """Test '设为' pattern variant."""
        base = {"height": 30.0}
        modified = apply_text_modifications(base, "高度设为 45")
        assert modified["height"] == 45.0

    def test_pattern_equals(self):
        """Test '=' pattern variant."""
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "外径=250")
        assert modified["diameter"] == 250.0

    def test_float_value(self):
        """Test decimal values."""
        base = {"fillet_radius": 3.0}
        modified = apply_text_modifications(base, "圆角改为 5.5")
        assert modified["fillet_radius"] == 5.5

    def test_thickness_alias(self):
        """Test '厚度' alias maps to 'thickness'."""
        base = {"thickness": 10.0}
        modified = apply_text_modifications(base, "厚度改为 15")
        assert modified["thickness"] == 15.0

    def test_width_alias(self):
        """Test '宽度' alias maps to 'width'."""
        base = {"width": 50.0}
        modified = apply_text_modifications(base, "宽度改为 80")
        assert modified["width"] == 80.0

    def test_length_alias(self):
        """Test '长度' alias maps to 'length'."""
        base = {"length": 200.0}
        modified = apply_text_modifications(base, "长度改为 300")
        assert modified["length"] == 300.0

    def test_unknown_param_skipped(self):
        """When modification mentions unknown param with no alias match, skip it."""
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "颜色改为 5")
        # "颜色" has no alias and no key match → skip
        assert modified == base

    def test_english_text_not_matched(self):
        """English text should not trigger modification (Chinese-only regex)."""
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "diameter改为 200")
        # "diameter" is not Chinese characters → no match
        assert modified["diameter"] == 100.0

    def test_original_not_mutated(self):
        """Ensure original dict is not mutated."""
        base = {"diameter": 100.0}
        modified = apply_text_modifications(base, "外径改为 200")
        assert base["diameter"] == 100.0
        assert modified["diameter"] == 200.0


class TestImageAnalyzer:
    def test_init_with_mock(self):
        async def mock_vl(image_bytes: bytes):
            return ImageAnalysisResult(
                part_type=PartType.ROTATIONAL,
                extracted_params={"diameter": 100},
                description="圆盘",
                confidence=0.9,
            )

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        assert analyzer is not None

    @pytest.mark.asyncio
    async def test_analyze_image(self):
        async def mock_vl(image_bytes: bytes):
            return ImageAnalysisResult(
                part_type=PartType.ROTATIONAL,
                extracted_params={"diameter": 100, "height": 30},
                description="法兰盘",
                confidence=0.85,
            )

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        result = await analyzer.analyze(b"fake_image")
        assert result is not None
        assert result.part_type == PartType.ROTATIONAL
        assert result.extracted_params["diameter"] == 100

    @pytest.mark.asyncio
    async def test_analyze_with_text_modification(self):
        async def mock_vl(image_bytes: bytes):
            return ImageAnalysisResult(
                part_type=PartType.ROTATIONAL,
                extracted_params={"diameter": 100, "height": 30},
                description="法兰盘",
                confidence=0.85,
            )

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        result = await analyzer.analyze_with_modifications(
            b"fake_image", "外径改为 150"
        )
        assert result is not None
        assert result.extracted_params["diameter"] == 150.0

    @pytest.mark.asyncio
    async def test_analyze_with_modifications_preserves_other_fields(self):
        async def mock_vl(image_bytes: bytes):
            return ImageAnalysisResult(
                part_type=PartType.PLATE,
                extracted_params={"width": 100, "length": 200, "thickness": 10},
                description="矩形板件",
                confidence=0.80,
            )

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        result = await analyzer.analyze_with_modifications(
            b"fake_image", "厚度改为 20"
        )
        assert result is not None
        assert result.part_type == PartType.PLATE
        assert result.description == "矩形板件"
        assert result.confidence == 0.80
        assert result.extracted_params["thickness"] == 20.0
        assert result.extracted_params["width"] == 100
        assert result.extracted_params["length"] == 200

    @pytest.mark.asyncio
    async def test_vl_failure_returns_none(self):
        async def mock_vl(image_bytes: bytes):
            return None

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        result = await analyzer.analyze(b"fake_image")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_with_modifications_vl_failure(self):
        async def mock_vl(image_bytes: bytes):
            return None

        analyzer = ImageAnalyzer(vl_fn=mock_vl)
        result = await analyzer.analyze_with_modifications(
            b"fake_image", "外径改为 150"
        )
        assert result is None
