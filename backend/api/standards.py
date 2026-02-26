"""Engineering standards API — browse, recommend, check.

Provides RESTful endpoints for the engineering standards knowledge base:
- GET    /standards              list all standard categories
- GET    /standards/{category}   get all entries in a category
- POST   /standards/recommend    recommend params based on known values
- POST   /standards/check        check engineering constraints
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.engineering_standards import (
    ConstraintViolation,
    EngineeringStandards,
    ParamRecommendation,
    StandardEntry,
)

router = APIRouter()

# Standards directory — overridable for testing via monkeypatch.
_STANDARDS_DIR = Path(__file__).parent.parent / "knowledge" / "standards"


def _get_standards() -> EngineeringStandards:
    """Load a fresh standards instance."""
    return EngineeringStandards(standards_dir=_STANDARDS_DIR)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RecommendRequest(BaseModel):
    """Request body for parameter recommendation."""

    part_type: str
    known_params: dict[str, float]


class RecommendResponse(BaseModel):
    """Response for parameter recommendation."""

    recommendations: list[ParamRecommendation]


class CheckRequest(BaseModel):
    """Request body for constraint checking."""

    part_type: str
    params: dict[str, float]


class CheckResponse(BaseModel):
    """Response for constraint checking."""

    valid: bool
    violations: list[ConstraintViolation]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/standards")
async def list_categories() -> list[str]:
    """List all standard categories."""
    eng = _get_standards()
    return eng.list_categories()


@router.get("/standards/{category}")
async def get_category(category: str) -> list[dict[str, Any]]:
    """Get all entries in a standard category."""
    eng = _get_standards()
    entries = eng.get_category(category)
    return [e.model_dump() for e in entries]


@router.post("/standards/recommend")
async def recommend_params(body: RecommendRequest) -> RecommendResponse:
    """Recommend missing parameters based on engineering standards."""
    eng = _get_standards()
    recs = eng.recommend_params(body.part_type, body.known_params)
    return RecommendResponse(recommendations=recs)


@router.post("/standards/check")
async def check_constraints(body: CheckRequest) -> CheckResponse:
    """Check engineering constraints on given parameters."""
    eng = _get_standards()
    violations = eng.check_constraints(body.part_type, body.params)
    return CheckResponse(valid=len(violations) == 0, violations=violations)
