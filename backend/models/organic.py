"""Pydantic models for the organic generation pipeline.

EngineeringCut uses discriminated union — each cut type has its own
model with type-specific required fields and value constraints.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Engineering cut types (discriminated union on "type")
# ---------------------------------------------------------------------------

class FlatBottomCut(BaseModel):
    """Flat bottom cut for stable 3D printing placement."""
    type: Literal["flat_bottom"] = "flat_bottom"
    offset: float = Field(default=0.0, ge=0.0, description="Offset from bottom in mm")


class HoleCut(BaseModel):
    """Cylindrical hole cut."""
    type: Literal["hole"] = "hole"
    diameter: float = Field(..., gt=0, le=200, description="Hole diameter in mm")
    depth: float = Field(..., gt=0, le=500, description="Hole depth in mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"


class SlotCut(BaseModel):
    """Rectangular slot cut."""
    type: Literal["slot"] = "slot"
    width: float = Field(..., gt=0, le=200, description="Slot width in mm")
    depth: float = Field(..., gt=0, le=500, description="Slot depth in mm")
    length: float = Field(..., gt=0, le=500, description="Slot length in mm")
    position: tuple[float, float, float] = (0, 0, 0)
    direction: Literal["top", "bottom", "front", "back", "left", "right"] = "bottom"


EngineeringCut = Annotated[
    FlatBottomCut | HoleCut | SlotCut,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Constraints & request
# ---------------------------------------------------------------------------

class OrganicConstraints(BaseModel):
    """Engineering constraints for organic model post-processing."""
    bounding_box: tuple[float, float, float] | None = None
    engineering_cuts: list[EngineeringCut] = Field(default_factory=list)


class OrganicGenerateRequest(BaseModel):
    """Request body for organic generation endpoint."""
    prompt: str = Field(..., min_length=1, max_length=2000)
    reference_image: str | None = None
    constraints: OrganicConstraints = Field(default_factory=OrganicConstraints)
    quality_mode: Literal["draft", "standard", "high"] = "standard"
    provider: Literal["auto", "tripo3d", "hunyuan3d"] = "auto"


# ---------------------------------------------------------------------------
# OrganicSpec (LLM-constructed)
# ---------------------------------------------------------------------------

class OrganicSpec(BaseModel):
    """Spec built by OrganicSpecBuilder from user input + LLM."""
    prompt_en: str
    prompt_original: str
    shape_category: str
    suggested_bounding_box: tuple[float, float, float] | None = None
    final_bounding_box: tuple[float, float, float] | None = None
    engineering_cuts: list[EngineeringCut] = Field(default_factory=list)
    quality_mode: Literal["draft", "standard", "high"] = "standard"
    negative_prompt: str = ""


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class MeshStats(BaseModel):
    """Mesh quality statistics after post-processing."""
    vertex_count: int
    face_count: int
    is_watertight: bool
    volume_cm3: float | None = None
    bounding_box: dict[str, float]
    has_non_manifold: bool
    repairs_applied: list[str] = Field(default_factory=list)
    boolean_cuts_applied: int = 0


class OrganicJobResult(BaseModel):
    """Result payload for a completed organic generation job."""
    job_id: str
    model_url: str
    stl_url: str | None = None
    threemf_url: str | None = None
    mesh_stats: MeshStats
    provider_used: str
    generation_time_s: float
    post_processing_time_s: float
