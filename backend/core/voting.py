"""Multi-model voting and self-consistency aggregation.

Aggregates multiple DrawingSpec results from different models or
repeated inferences of the same model:
- Numeric fields: median (robust to outliers)
- Categorical fields: majority vote
- Inconsistent fields: flagged as low confidence

Controlled by PipelineConfig:
- multi_model_voting (bool): enable multi-model aggregation
- self_consistency_runs (int, 1=off): same-model repetition count
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

from ..knowledge.part_types import BaseBodySpec, DrawingSpec, PartType


def aggregate_numeric(values: list[float]) -> Optional[float]:
    """Aggregate numeric values using median.

    Returns None for empty input.
    """
    if not values:
        return None
    return statistics.median(values)


def aggregate_categorical(values: list[str]) -> Optional[str]:
    """Aggregate categorical values using majority vote.

    Returns None for empty input. On tie, returns the first-seen value
    (CPython Counter.most_common behavior).
    """
    if not values:
        return None
    counter = Counter(values)
    return counter.most_common(1)[0][0]


@dataclass
class FieldConfidence:
    """Confidence assessment for a single aggregated field.

    For numeric fields: uses coefficient of variation (CV = stdev / |mean|).
      - CV < 0.1 is considered consistent.
      - confidence = clamp(1.0 - CV, 0, 1)

    For categorical fields: uses agreement ratio (top_count / total).
      - agreement > 0.5 is considered consistent.
      - confidence = agreement ratio
    """

    confidence: float
    is_consistent: bool
    values: list[object] = field(default_factory=list)

    @classmethod
    def from_values(cls, values: list) -> FieldConfidence:
        """Compute confidence from a list of values.

        Automatically detects numeric vs categorical based on value types.
        Handles edge cases: empty list, single element, zero mean.
        """
        if not values:
            return cls(confidence=0.0, is_consistent=False)

        # Numeric path
        if all(isinstance(v, (int, float)) for v in values):
            mean = statistics.mean(values)
            if mean == 0:
                # All zeros → perfectly consistent; mixed with zeros handled
                # by checking if all values are equal
                if all(v == 0 for v in values):
                    cv = 0.0
                else:
                    # Non-zero values with zero mean: use stdev as proxy
                    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
                    cv = float("inf") if stdev > 0 else 0.0
            else:
                stdev = statistics.stdev(values) if len(values) > 1 else 0.0
                cv = stdev / abs(mean)
            is_consistent = cv < 0.1
            confidence = max(0.0, min(1.0, 1.0 - cv))
            return cls(
                confidence=confidence, is_consistent=is_consistent, values=values
            )

        # Categorical path
        counter = Counter(values)
        total = len(values)
        top_count = counter.most_common(1)[0][1]
        agreement = top_count / total
        return cls(
            confidence=agreement,
            is_consistent=agreement > 0.5,
            values=values,
        )


@dataclass
class AggregatedResult:
    """Result of aggregating multiple DrawingSpec instances.

    Attributes:
        spec: The aggregated DrawingSpec with merged fields.
        field_confidences: Per-field confidence and consistency flags.
        source_count: Number of input specs used.
    """

    spec: DrawingSpec
    field_confidences: dict[str, FieldConfidence] = field(default_factory=dict)
    source_count: int = 0


class VotingAggregator:
    """Aggregates multiple DrawingSpec results into a single consensus spec.

    Usage:
        aggregator = VotingAggregator()
        result = aggregator.aggregate([spec1, spec2, spec3])
        if result:
            print(result.spec)  # merged DrawingSpec
            print(result.field_confidences)  # per-field confidence
    """

    def aggregate(
        self, specs: list[DrawingSpec]
    ) -> Optional[AggregatedResult]:
        """Aggregate multiple DrawingSpec into a single consensus result.

        Returns None for empty input. Single spec is returned as-is with
        source_count=1. For multiple specs, numeric fields use median and
        categorical fields use majority vote.

        Features are taken from the first spec (simplified merging;
        full feature merging is deferred to Phase 6).
        """
        if not specs:
            return None
        if len(specs) == 1:
            return AggregatedResult(spec=specs[0], source_count=1)

        confidences: dict[str, FieldConfidence] = {}

        # --- Aggregate part_type (categorical) ---
        part_types = [s.part_type.value for s in specs]
        agg_type = aggregate_categorical(part_types)
        confidences["part_type"] = FieldConfidence.from_values(part_types)

        # --- Aggregate overall_dimensions (numeric per key) ---
        all_dim_keys: set[str] = set()
        for s in specs:
            all_dim_keys.update(s.overall_dimensions.keys())

        agg_dims: dict[str, float] = {}
        for key in sorted(all_dim_keys):
            vals = [
                s.overall_dimensions[key]
                for s in specs
                if key in s.overall_dimensions
            ]
            median_val = aggregate_numeric(vals)
            if median_val is not None:
                agg_dims[key] = median_val
            confidences[key] = FieldConfidence.from_values(vals)

        # --- Aggregate base_body.method (categorical) ---
        methods = [s.base_body.method for s in specs if s.base_body.method]
        agg_method = aggregate_categorical(methods) if methods else "extrude"

        # --- Features: take from first spec (simplified) ---
        agg_features = specs[0].features

        # --- Build aggregated DrawingSpec ---
        agg_spec = DrawingSpec(
            part_type=agg_type,
            description=specs[0].description,
            overall_dimensions=agg_dims,
            base_body=BaseBodySpec(method=agg_method),
            features=agg_features,
        )

        return AggregatedResult(
            spec=agg_spec,
            field_confidences=confidences,
            source_count=len(specs),
        )
