"""Reference image understanding: VL analysis + text modification overlay.

Provides ``ImageAnalyzer`` for extracting structured parameters from a
reference image via a vision-language model, and ``apply_text_modifications``
for overlaying natural-language dimension changes on top of the VL result.

In tests, inject a mock ``vl_fn`` to avoid real API calls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

from ..knowledge.part_types import PartType


# ---------------------------------------------------------------------------
# Param name aliases (Chinese → canonical English)
# ---------------------------------------------------------------------------

_PARAM_ALIASES: dict[str, str] = {
    "外径": "diameter",
    "直径": "diameter",
    "内径": "bore_diameter",
    "高度": "height",
    "总高": "height",
    "厚度": "thickness",
    "宽度": "width",
    "长度": "length",
    "通孔直径": "bore_diameter",
    "孔径": "bore_diameter",
    "圆角": "fillet_radius",
    "倒角": "chamfer_size",
}

# ---------------------------------------------------------------------------
# Modification pattern: captures Chinese param name + numeric value
#
# Supported forms:
#   外径改为 150 / 高度改成 50 / 厚度设为 20 / 外径=250
#   将外径改为 150
# ---------------------------------------------------------------------------

_MOD_PATTERN = re.compile(
    r"(?:将\s*)?([\u4e00-\u9fff]+)\s*(?:改为|改成|设为|=)\s*(\d+(?:\.\d+)?)"
)


# ---------------------------------------------------------------------------
# ImageAnalysisResult
# ---------------------------------------------------------------------------


@dataclass
class ImageAnalysisResult:
    """Result of VL image analysis."""

    part_type: Optional[PartType]
    extracted_params: dict[str, float] = field(default_factory=dict)
    description: str = ""
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Type alias for the async VL callable
# ---------------------------------------------------------------------------

VLFn = Callable[[bytes], Awaitable[Optional[ImageAnalysisResult]]]


# ---------------------------------------------------------------------------
# Text modification overlay
# ---------------------------------------------------------------------------


def apply_text_modifications(
    base_params: dict[str, float],
    modification_text: str,
) -> dict[str, float]:
    """Apply natural-language dimension modifications to *base_params*.

    Parses patterns like "外径改为 150", "高度改成 50", "直径=200" from
    ``modification_text`` and updates the corresponding canonical parameter.

    Parameters
    ----------
    base_params:
        Base parameter dict (not mutated).
    modification_text:
        Chinese text containing modification instructions.

    Returns
    -------
    A new dict with modifications applied.
    """
    result = dict(base_params)

    for match in _MOD_PATTERN.finditer(modification_text):
        param_cn = match.group(1)
        value = float(match.group(2))

        # 1. Try alias lookup
        canonical = _PARAM_ALIASES.get(param_cn)
        if canonical is not None:
            result[canonical] = value
            continue

        # 2. Fallback: substring match against existing keys
        matched = False
        for key in result:
            if param_cn in key:
                result[key] = value
                matched = True
                break

    return result


# ---------------------------------------------------------------------------
# ImageAnalyzer
# ---------------------------------------------------------------------------


class ImageAnalyzer:
    """Analyze reference images via an injected VL function.

    Parameters
    ----------
    vl_fn:
        An async callable ``(image_bytes) -> Optional[ImageAnalysisResult]``.
        In production this wraps the real VL model; in tests a mock is
        injected.
    """

    def __init__(self, vl_fn: VLFn) -> None:
        self._vl_fn = vl_fn

    async def analyze(
        self, image_bytes: bytes
    ) -> Optional[ImageAnalysisResult]:
        """Analyze an image and return structured parameters."""
        return await self._vl_fn(image_bytes)

    async def analyze_with_modifications(
        self,
        image_bytes: bytes,
        modification_text: str,
    ) -> Optional[ImageAnalysisResult]:
        """Analyze an image, then overlay text modifications.

        1. Call VL to get base result
        2. Apply ``modification_text`` to adjust parameters
        3. Return a new ``ImageAnalysisResult`` with modified params
        """
        result = await self._vl_fn(image_bytes)
        if result is None:
            return None

        modified_params = apply_text_modifications(
            result.extracted_params,
            modification_text,
        )

        return ImageAnalysisResult(
            part_type=result.part_type,
            extracted_params=modified_params,
            description=result.description,
            confidence=result.confidence,
        )
