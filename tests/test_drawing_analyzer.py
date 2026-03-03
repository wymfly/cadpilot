"""Tests for DrawingAnalyzer CoT parsing + OCR-VLM fusion."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.drawing_analyzer import _parse_drawing_spec


class TestParseDrawingSpecCoT:
    def test_parse_with_reasoning_and_json(self):
        """CoT format: reasoning block then JSON block."""
        text = '''
```reasoning
1. 从正视图可见：外径标注 φ100，中间凸台 φ40，顶部 φ24
2. 从俯视图可见：6 个均布孔，PCD=70
3. 高度判断：底层 10mm + 中间 10mm + 顶部 10mm = 30mm
4. 零件类型：多层阶梯 + 中心通孔 → rotational_stepped
5. 建模方式：revolve（旋转体首选）
```

```json
{
  "part_type": "rotational_stepped",
  "description": "三层阶梯法兰盘",
  "views": ["front_section", "top"],
  "overall_dimensions": {"max_diameter": 100, "total_height": 30},
  "base_body": {
    "method": "revolve",
    "profile": [
      {"diameter": 100, "height": 10, "label": "base_flange"},
      {"diameter": 40, "height": 10, "label": "middle_boss"},
      {"diameter": 24, "height": 10, "label": "top_boss"}
    ],
    "bore": {"diameter": 10, "through": true}
  },
  "features": [
    {"type": "hole_pattern", "pattern": "circular", "count": 6, "diameter": 10, "pcd": 70}
  ],
  "notes": []
}
```
'''
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is not None
        assert result["result"].part_type.value == "rotational_stepped"
        assert result["result"].overall_dimensions["max_diameter"] == 100
        assert result["reasoning"] is not None
        assert "φ100" in result["reasoning"]

    def test_parse_without_reasoning(self):
        """Backward compat: no reasoning block, just JSON."""
        text = '''```json
{"part_type": "plate", "description": "test plate", "views": [],
 "overall_dimensions": {}, "base_body": {"method": "extrude"},
 "features": [], "notes": []}
```'''
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is not None
        assert result["result"].part_type.value == "plate"
        assert result["reasoning"] is None

    def test_parse_bare_json(self):
        """No code blocks at all, just raw JSON."""
        text = '{"part_type": "general", "description": "x", "views": [], "overall_dimensions": {}, "base_body": {"method": "extrude"}, "features": [], "notes": []}'
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is not None
        assert result["result"].part_type.value == "general"

    def test_invalid_json_returns_none(self):
        """Invalid JSON returns result=None but still extracts reasoning."""
        text = '''
```reasoning
Some analysis here
```

```json
{invalid json!!!}
```
'''
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is None
        assert result["reasoning"] is not None
        assert "Some analysis" in result["reasoning"]

    def test_parse_adjacent_code_blocks_shared_delimiter(self):
        """VL model output where reasoning and json blocks share a ``` delimiter.

        Real VL output format: ```reasoning\\n...\\n```json\\n...\\n```
        The middle ``` is both the end of reasoning and the start of json.
        """
        text = '```reasoning\n1. 视图识别：左侧为俯视图\n2. 尺寸提取：外径 φ100\n```json\n{"part_type": "rotational_stepped", "description": "阶梯轴", "views": ["top", "front_section"], "overall_dimensions": {"max_diameter": 100, "total_height": 30}, "base_body": {"method": "revolve", "profile": [{"diameter": 100, "height": 10, "label": "outer"}], "bore": {"diameter": 10, "through": true}}, "features": [], "notes": []}\n```'
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is not None, "Should parse JSON even with shared delimiter"
        assert result["result"].part_type.value == "rotational_stepped"
        assert result["result"].overall_dimensions["max_diameter"] == 100

    def test_invalid_part_type_defaults_to_general(self):
        """Unknown part_type is replaced with 'general'."""
        text = '{"part_type": "unknown_type", "description": "x", "views": [], "overall_dimensions": {}, "base_body": {"method": "extrude"}, "features": [], "notes": []}'
        result = _parse_drawing_spec({"text": text})
        assert result["result"] is not None
        assert result["result"].part_type.value == "general"


# ===================================================================
# OCR-VLM Fusion tests (T15)
# ===================================================================


class TestMapOcrToVlKeys:
    """Tests for _map_ocr_to_vl_keys heuristic mapping."""

    def test_diameter_matching(self) -> None:
        from backend.core.drawing_analyzer import _map_ocr_to_vl_keys
        from backend.core.ocr_assist import DimensionAnnotation

        annotations = [DimensionAnnotation(type="diameter", value=50.0)]
        vl_dims = {"max_diameter": 48.0, "total_height": 30.0}
        result = _map_ocr_to_vl_keys(annotations, vl_dims)
        assert result["max_diameter"] == 50.0
        assert "total_height" not in result

    def test_linear_matching(self) -> None:
        from backend.core.drawing_analyzer import _map_ocr_to_vl_keys
        from backend.core.ocr_assist import DimensionAnnotation

        annotations = [DimensionAnnotation(type="linear", value=30.0)]
        vl_dims = {"max_diameter": 100.0, "total_height": 28.0}
        result = _map_ocr_to_vl_keys(annotations, vl_dims)
        assert result["total_height"] == 30.0
        assert "max_diameter" not in result

    def test_multiple_diameters_sorted(self) -> None:
        """Multiple OCR diameters matched to multiple VL diameter keys by size."""
        from backend.core.drawing_analyzer import _map_ocr_to_vl_keys
        from backend.core.ocr_assist import DimensionAnnotation

        annotations = [
            DimensionAnnotation(type="diameter", value=100.0),
            DimensionAnnotation(type="diameter", value=40.0),
        ]
        vl_dims = {"max_diameter": 98.0, "inner_diameter": 38.0}
        result = _map_ocr_to_vl_keys(annotations, vl_dims)
        assert result["max_diameter"] == 100.0
        assert result["inner_diameter"] == 40.0

    def test_no_matching_keys(self) -> None:
        """No VL keys match OCR types — empty dict."""
        from backend.core.drawing_analyzer import _map_ocr_to_vl_keys
        from backend.core.ocr_assist import DimensionAnnotation

        annotations = [DimensionAnnotation(type="diameter", value=50.0)]
        vl_dims = {"some_other_key": 100.0}
        result = _map_ocr_to_vl_keys(annotations, vl_dims)
        assert result == {}

    def test_empty_annotations(self) -> None:
        from backend.core.drawing_analyzer import _map_ocr_to_vl_keys

        result = _map_ocr_to_vl_keys([], {"max_diameter": 100.0})
        assert result == {}


class TestFuseOcrWithSpec:
    """Tests for fuse_ocr_with_spec end-to-end fusion."""

    def _make_spec(self, dims: dict[str, float]) -> MagicMock:
        """Create a mock DrawingSpec with given overall_dimensions."""
        spec = MagicMock()
        spec.overall_dimensions = dims.copy()
        return spec

    def test_ocr_overrides_vl_for_numeric(self) -> None:
        """When OCR and VLM disagree on a number, OCR wins."""
        from backend.core.ocr_assist import DimensionAnnotation, merge_ocr_with_vl

        merged, conf = merge_ocr_with_vl(
            ocr_dims={"diameter": 50.0},
            vl_dims={"diameter": 48.0, "height": 30.0},
        )
        assert merged["diameter"] == 50.0  # OCR wins
        assert merged["height"] == 30.0  # VLM only
        assert conf["diameter"] == 0.7  # Disagreement confidence

    def test_fuse_with_mocked_ocr(self) -> None:
        """Full fusion with mocked OCR engine."""
        from backend.core.drawing_analyzer import fuse_ocr_with_spec
        from backend.core.ocr_assist import OCRResult

        spec = self._make_spec({"max_diameter": 48.0, "total_height": 30.0})

        mock_ocr_fn = MagicMock(return_value=[
            OCRResult(text="φ50", confidence=0.95, bbox=(10, 20, 100, 40)),
            OCRResult(text="32", confidence=0.90, bbox=(10, 60, 100, 80)),
        ])

        with patch("backend.core.ocr_engine.get_ocr_fn", return_value=mock_ocr_fn):
            result = fuse_ocr_with_spec(spec, b"fake image bytes")

        # OCR found Ø50 (diameter=50) and 32 (linear=32)
        assert result.overall_dimensions["max_diameter"] == 50.0
        assert result.overall_dimensions["total_height"] == 32.0

    def test_fuse_no_ocr_dims_returns_original(self) -> None:
        """When OCR finds nothing, spec is unchanged."""
        from backend.core.drawing_analyzer import fuse_ocr_with_spec

        spec = self._make_spec({"max_diameter": 100.0})
        mock_ocr_fn = MagicMock(return_value=[])

        with patch("backend.core.ocr_engine.get_ocr_fn", return_value=mock_ocr_fn):
            result = fuse_ocr_with_spec(spec, b"fake image")

        assert result.overall_dimensions["max_diameter"] == 100.0

    def test_fuse_graceful_on_ocr_failure(self) -> None:
        """When OCR extraction fails, spec is unchanged."""
        from backend.core.drawing_analyzer import fuse_ocr_with_spec

        spec = self._make_spec({"max_diameter": 100.0})
        mock_ocr_fn = MagicMock(side_effect=RuntimeError("OCR crashed"))

        with patch("backend.core.ocr_engine.get_ocr_fn", return_value=mock_ocr_fn):
            result = fuse_ocr_with_spec(spec, b"fake image")

        assert result.overall_dimensions["max_diameter"] == 100.0
