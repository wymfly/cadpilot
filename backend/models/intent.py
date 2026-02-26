"""IntentSpec / PreciseSpec data models for V3 Phase 4 interactive workflow.

IntentSpec captures the structured representation of a user's natural-language
intent (output of IntentParser).  PreciseSpec extends DrawingSpec with
provenance and confirmation metadata, representing a fully-specified part
after user confirmation.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.knowledge.part_types import (
    BaseBodySpec,
    DrawingSpec,
    PartType,
)


# ---------------------------------------------------------------------------
# IntentSpec
# ---------------------------------------------------------------------------


class IntentSpec(BaseModel):
    """User intent structured representation -- output of IntentParser."""

    part_category: str = ""
    part_type: Optional[PartType] = None
    known_params: dict[str, float] = Field(default_factory=dict)
    missing_params: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    reference_image: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# ParamRecommendation
# ---------------------------------------------------------------------------


class ParamRecommendation(BaseModel):
    """Single parameter recommendation from EngineeringStandards."""

    param_name: str
    value: float
    unit: str = "mm"
    reason: str
    source: str = ""


# ---------------------------------------------------------------------------
# PreciseSpec
# ---------------------------------------------------------------------------


class PreciseSpec(DrawingSpec):
    """Fully-specified part spec after user confirmation.

    Inherits every field from DrawingSpec and adds provenance /
    confirmation metadata.
    """

    source: Literal["text_input", "drawing_input", "image_input"] = (
        "text_input"
    )
    confirmed_by_user: bool = True
    intent: Optional[IntentSpec] = None
    recommendations_applied: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversion helper
# ---------------------------------------------------------------------------


def intent_to_precise(
    intent: IntentSpec,
    confirmed_params: dict[str, float],
    base_body_method: str = "extrude",
) -> PreciseSpec:
    """Convert an IntentSpec + user-confirmed params into a PreciseSpec.

    Parameters
    ----------
    intent:
        The parsed user intent.
    confirmed_params:
        Parameters confirmed (or adjusted) by the user.  These override
        ``intent.known_params`` on key collision.
    base_body_method:
        The construction method for the base body (default ``"extrude"``).

    Returns
    -------
    PreciseSpec
        A fully-specified part ready for code generation.
    """
    # Merge: intent.known_params as base, confirmed_params overrides
    merged_params: dict[str, float] = {
        **intent.known_params,
        **confirmed_params,
    }

    # Determine part_type; fall back to GENERAL when unknown
    part_type = intent.part_type or PartType.GENERAL

    # Build base body from merged params (extract dimension hints)
    base_body = BaseBodySpec(
        method=base_body_method,
        width=merged_params.get("width"),
        length=merged_params.get("length"),
        height=merged_params.get("height"),
    )

    # Track which confirmed_params keys were applied
    applied = [k for k in confirmed_params if k in merged_params]

    return PreciseSpec(
        part_type=part_type,
        description=intent.part_category or part_type.value,
        overall_dimensions=merged_params,
        base_body=base_body,
        source="text_input",
        confirmed_by_user=True,
        intent=intent,
        recommendations_applied=applied,
    )
