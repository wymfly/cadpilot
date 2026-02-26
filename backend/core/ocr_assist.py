"""OCR-assisted dimension extraction from engineering drawings.

Uses dependency-injected OCR function for testability.
Real OCR: PaddleOCR or Tesseract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class OCRResult:
    """Single OCR detection result."""

    text: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2


@dataclass
class DimensionAnnotation:
    """Parsed dimension annotation from OCR text."""

    type: str  # "diameter", "radius", "linear", "angle"
    value: float
    symbol: str = ""
    tolerance: Optional[float] = None
    count: Optional[int] = None


# Type alias for OCR function: image bytes -> list of OCR results
OCRFn = Callable[[bytes], list[OCRResult]]


def parse_dimension_text(text: str) -> Optional[DimensionAnnotation]:
    """Parse a single OCR text string into a DimensionAnnotation.

    Recognized patterns:
    - N*phiD (e.g. "6*phi10") -> diameter with count
    - phiD (e.g. "phi50") -> diameter
    - RN (e.g. "R15") -> radius (but NOT Ra surface finish)
    - N+-T (e.g. "50+-0.1") -> linear with tolerance
    - plain number (e.g. "120") -> linear

    Returns None for non-dimension text (e.g. Ra surface finish, free text).
    """
    text = text.strip()
    if not text:
        return None

    # Skip surface finish annotations (Ra/ra followed by digit)
    if re.match(r"[Rr]a\d", text):
        return None

    # Pattern: NxphiD (e.g. "6xphi10")
    m = re.match(r"(\d+)\s*[×x]\s*[φΦ](\d+(?:\.\d+)?)", text)
    if m:
        return DimensionAnnotation(
            type="diameter",
            value=float(m.group(2)),
            symbol="φ",
            count=int(m.group(1)),
        )

    # Pattern: phiD (e.g. "phi50")
    m = re.match(r"[φΦ](\d+(?:\.\d+)?)", text)
    if m:
        return DimensionAnnotation(
            type="diameter",
            value=float(m.group(1)),
            symbol="φ",
        )

    # Pattern: RN — radius, but not Ra (surface finish already filtered above)
    m = re.match(r"R(\d+(?:\.\d+)?)", text)
    if m:
        return DimensionAnnotation(
            type="radius",
            value=float(m.group(1)),
            symbol="R",
        )

    # Pattern: N+-T (e.g. "50+-0.1")
    m = re.match(r"(\d+(?:\.\d+)?)±(\d+(?:\.\d+)?)", text)
    if m:
        return DimensionAnnotation(
            type="linear",
            value=float(m.group(1)),
            tolerance=float(m.group(2)),
        )

    # Plain number
    m = re.match(r"^(\d+(?:\.\d+)?)$", text)
    if m:
        return DimensionAnnotation(
            type="linear",
            value=float(m.group(1)),
        )

    return None


def merge_ocr_with_vl(
    ocr_dims: dict[str, float],
    vl_dims: dict[str, object],
) -> tuple[dict[str, object], dict[str, float]]:
    """Merge OCR numeric results with VL semantic results.

    For numeric fields: OCR preferred (more accurate for exact numbers).
    For semantic fields: VL preferred (understands context better).
    Confidence scoring reflects agreement level.

    Returns:
        (merged_dict, confidence_dict) where confidence is 0.0-1.0 per key.
    """
    merged: dict[str, object] = {}
    confidence: dict[str, float] = {}

    all_keys = set(ocr_dims.keys()) | set(vl_dims.keys())
    for key in all_keys:
        ocr_val = ocr_dims.get(key)
        vl_val = vl_dims.get(key)

        if ocr_val is not None and vl_val is not None:
            # Both sources have a value for this key
            if isinstance(ocr_val, (int, float)) and isinstance(vl_val, (int, float)):
                # Both numeric — check agreement
                if abs(ocr_val - vl_val) < 0.01:
                    merged[key] = ocr_val
                    confidence[key] = 0.95  # High confidence: both agree
                else:
                    merged[key] = ocr_val  # OCR preferred for numeric
                    confidence[key] = 0.7  # Lower confidence: disagreement
            else:
                # At least one is non-numeric — VL preferred for semantic
                merged[key] = vl_val
                confidence[key] = 0.8
        elif ocr_val is not None:
            merged[key] = ocr_val
            confidence[key] = 0.85  # OCR-only, reasonably confident
        else:
            merged[key] = vl_val
            confidence[key] = 0.8  # VL-only, reasonably confident

    return merged, confidence


class OCRAssistant:
    """OCR-assisted dimension extraction with dependency-injected OCR function.

    Usage:
        assistant = OCRAssistant(ocr_fn=my_paddleocr_function)
        dims = assistant.extract_dimensions(image_bytes)
    """

    def __init__(self, ocr_fn: OCRFn) -> None:
        self._ocr_fn = ocr_fn

    def extract_dimensions(self, image_bytes: bytes) -> list[DimensionAnnotation]:
        """Run OCR on image and parse all recognized dimension annotations.

        Non-dimension text (surface finish, notes, etc.) is filtered out.
        """
        raw = self._ocr_fn(image_bytes)
        dims: list[DimensionAnnotation] = []
        for r in raw:
            parsed = parse_dimension_text(r.text)
            if parsed is not None:
                dims.append(parsed)
        return dims
