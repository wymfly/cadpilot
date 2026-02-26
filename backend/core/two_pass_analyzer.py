"""Two-pass drawing analysis: global structure first, then local dimensions.

Pass 1 identifies part type, step count, feature count, and views.
Pass 2 extracts detailed dimensions and feature specifications.
Both passes use dependency-injected async callables for testability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..knowledge.part_types import BaseBodySpec, DrawingSpec, PartType


@dataclass
class Pass1Result:
    """Pass 1 output: global structure identification."""

    part_type: PartType
    step_count: int
    feature_count: int
    views: list[str]


@dataclass
class Pass2Result:
    """Pass 2 output: detailed dimensions and features."""

    dimensions: dict[str, float]
    features: list[dict[str, Any]]


# Type aliases for injected analysis functions
Pass1Fn = Callable[[bytes], Awaitable[Optional[Pass1Result]]]
Pass2Fn = Callable[[bytes, Pass1Result], Awaitable[Pass2Result]]


class TwoPassAnalyzer:
    """Two-pass drawing analyzer with injected pass functions.

    Usage:
        analyzer = TwoPassAnalyzer(pass1_fn=my_vl_pass1, pass2_fn=my_vl_pass2)
        spec = await analyzer.analyze(image_bytes)
    """

    def __init__(self, pass1_fn: Pass1Fn, pass2_fn: Pass2Fn) -> None:
        self._pass1_fn = pass1_fn
        self._pass2_fn = pass2_fn

    async def analyze(self, image_bytes: bytes) -> Optional[DrawingSpec]:
        """Run two-pass analysis and return a DrawingSpec.

        Pass 1: Identify part type, structure, views.
        Pass 2: Extract detailed dimensions and features.

        Returns None if Pass 1 fails (cannot identify the part).
        """
        pass1 = await self._pass1_fn(image_bytes)
        if pass1 is None:
            return None

        pass2 = await self._pass2_fn(image_bytes, pass1)

        # Choose base body method based on part type
        method = (
            "revolve"
            if pass1.part_type
            in (PartType.ROTATIONAL, PartType.ROTATIONAL_STEPPED)
            else "extrude"
        )

        return DrawingSpec(
            part_type=pass1.part_type.value,
            description=f"{pass1.part_type.value} with {pass1.step_count} steps",
            views=pass1.views,
            overall_dimensions=pass2.dimensions,
            base_body=BaseBodySpec(method=method),
            features=pass2.features,
        )
