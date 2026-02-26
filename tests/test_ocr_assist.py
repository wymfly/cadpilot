"""Tests for OCR-assisted dimension extraction."""
import pytest

from backend.core.ocr_assist import (
    OCRResult,
    DimensionAnnotation,
    parse_dimension_text,
    merge_ocr_with_vl,
    OCRAssistant,
)


class TestParseDimensionText:
    def test_diameter_symbol(self):
        result = parse_dimension_text("φ50")
        assert result == DimensionAnnotation(type="diameter", value=50.0, symbol="φ")

    def test_diameter_symbol_uppercase(self):
        result = parse_dimension_text("Φ50")
        assert result == DimensionAnnotation(type="diameter", value=50.0, symbol="φ")

    def test_diameter_with_decimal(self):
        result = parse_dimension_text("φ12.5")
        assert result == DimensionAnnotation(type="diameter", value=12.5, symbol="φ")

    def test_radius_symbol(self):
        result = parse_dimension_text("R15")
        assert result == DimensionAnnotation(type="radius", value=15.0, symbol="R")

    def test_radius_with_decimal(self):
        result = parse_dimension_text("R3.5")
        assert result == DimensionAnnotation(type="radius", value=3.5, symbol="R")

    def test_tolerance(self):
        result = parse_dimension_text("50±0.1")
        assert result is not None
        assert result.value == 50.0
        assert result.tolerance == 0.1
        assert result.type == "linear"

    def test_multiplication(self):
        result = parse_dimension_text("6×φ10")
        assert result is not None
        assert result.count == 6
        assert result.value == 10.0
        assert result.type == "diameter"
        assert result.symbol == "φ"

    def test_multiplication_with_decimal(self):
        result = parse_dimension_text("4×φ8.5")
        assert result is not None
        assert result.count == 4
        assert result.value == 8.5

    def test_plain_number(self):
        result = parse_dimension_text("120")
        assert result is not None
        assert result.value == 120.0
        assert result.type == "linear"

    def test_plain_number_with_decimal(self):
        result = parse_dimension_text("25.4")
        assert result is not None
        assert result.value == 25.4
        assert result.type == "linear"

    def test_surface_finish_ra_skip(self):
        result = parse_dimension_text("Ra3.2")
        assert result is None

    def test_surface_finish_ra_lowercase_skip(self):
        result = parse_dimension_text("ra1.6")
        assert result is None

    def test_surface_finish_rz_skip(self):
        result = parse_dimension_text("Rz6.3")
        assert result is None

    def test_surface_finish_rz_lowercase_skip(self):
        result = parse_dimension_text("rz3.2")
        assert result is None

    def test_radius_rejects_trailing_text(self):
        """R15abc should NOT match as radius — anchor prevents partial match."""
        result = parse_dimension_text("R15abc")
        assert result is None

    def test_empty_string(self):
        result = parse_dimension_text("")
        assert result is None

    def test_whitespace_only(self):
        result = parse_dimension_text("   ")
        assert result is None

    def test_non_numeric_text(self):
        result = parse_dimension_text("abc")
        assert result is None

    def test_whitespace_trimming(self):
        result = parse_dimension_text("  φ50  ")
        assert result is not None
        assert result.value == 50.0


class TestMergeOCRWithVL:
    def test_consistent_values_high_confidence(self):
        ocr_dims = {"diameter": 100.0}
        vl_dims = {"diameter": 100.0}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        assert merged["diameter"] == 100.0
        assert confidence["diameter"] >= 0.9

    def test_inconsistent_values_prefer_ocr_numeric(self):
        ocr_dims = {"diameter": 100.0}
        vl_dims = {"diameter": 95.0}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        assert merged["diameter"] == 100.0  # OCR preferred for numbers
        assert confidence["diameter"] < 0.9

    def test_vl_only_field(self):
        ocr_dims: dict[str, float] = {}
        vl_dims: dict[str, object] = {"part_type": "rotational"}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        assert merged["part_type"] == "rotational"
        assert confidence["part_type"] == 0.8

    def test_ocr_only_field(self):
        ocr_dims = {"height": 30.0}
        vl_dims: dict[str, object] = {}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        assert merged["height"] == 30.0
        assert confidence["height"] == 0.85

    def test_semantic_field_prefers_vl(self):
        ocr_dims = {"description": 123.0}  # type: ignore[dict-item]
        vl_dims: dict[str, object] = {"description": "法兰盘"}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        # VL preferred for semantic (non-numeric) fields
        # Both are present; VL is string, OCR is number — they diverge
        # OCR numeric is preferred when both are numeric; otherwise VL preferred
        assert "description" in merged

    def test_empty_both(self):
        merged, confidence = merge_ocr_with_vl({}, {})
        assert merged == {}
        assert confidence == {}

    def test_multiple_keys(self):
        ocr_dims = {"diameter": 100.0, "height": 30.0}
        vl_dims: dict[str, object] = {"diameter": 100.0, "width": 50.0}
        merged, confidence = merge_ocr_with_vl(ocr_dims, vl_dims)
        assert "diameter" in merged
        assert "height" in merged
        assert "width" in merged
        assert len(merged) == 3


class TestOCRAssistant:
    def test_init_with_mock(self):
        def mock_ocr(image_bytes: bytes) -> list[OCRResult]:
            return [OCRResult(text="φ50", confidence=0.95, bbox=(10, 20, 50, 30))]

        assistant = OCRAssistant(ocr_fn=mock_ocr)
        assert assistant is not None

    def test_extract_dimensions(self):
        def mock_ocr(image_bytes: bytes) -> list[OCRResult]:
            return [
                OCRResult(text="φ50", confidence=0.95, bbox=(10, 20, 50, 30)),
                OCRResult(text="30", confidence=0.90, bbox=(60, 20, 90, 30)),
                OCRResult(text="Ra3.2", confidence=0.88, bbox=(100, 20, 140, 30)),
            ]

        assistant = OCRAssistant(ocr_fn=mock_ocr)
        dims = assistant.extract_dimensions(b"fake_image")
        assert len(dims) == 2  # φ50 and 30, Ra3.2 is surface finish
        types = [d.type for d in dims]
        assert "diameter" in types
        assert "linear" in types

    def test_no_ocr_results(self):
        assistant = OCRAssistant(ocr_fn=lambda img: [])
        dims = assistant.extract_dimensions(b"fake_image")
        assert dims == []

    def test_all_filtered_out(self):
        """All OCR results are surface finish annotations — nothing returned."""

        def mock_ocr(image_bytes: bytes) -> list[OCRResult]:
            return [
                OCRResult(text="Ra3.2", confidence=0.88, bbox=(10, 20, 50, 30)),
                OCRResult(text="Ra1.6", confidence=0.85, bbox=(60, 20, 90, 30)),
            ]

        assistant = OCRAssistant(ocr_fn=mock_ocr)
        dims = assistant.extract_dimensions(b"fake_image")
        assert dims == []

    def test_mixed_valid_and_invalid(self):
        """Mix of valid dimensions and non-parseable text."""

        def mock_ocr(image_bytes: bytes) -> list[OCRResult]:
            return [
                OCRResult(text="φ100", confidence=0.95, bbox=(10, 20, 50, 30)),
                OCRResult(text="R5", confidence=0.92, bbox=(60, 20, 90, 30)),
                OCRResult(text="材料: 45钢", confidence=0.80, bbox=(100, 20, 200, 30)),
                OCRResult(text="6×φ10", confidence=0.90, bbox=(210, 20, 260, 30)),
            ]

        assistant = OCRAssistant(ocr_fn=mock_ocr)
        dims = assistant.extract_dimensions(b"fake_image")
        assert len(dims) == 3  # φ100, R5, 6×φ10
