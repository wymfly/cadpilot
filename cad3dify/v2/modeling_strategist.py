"""Modeling strategist: selects building strategy and few-shot examples.

Feature-based example selection uses Jaccard similarity between the features
extracted from a DrawingSpec and the ``features`` frozenset of each TaggedExample.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..knowledge.examples import EXAMPLES_BY_TYPE, TaggedExample, get_tagged_examples
from ..knowledge.modeling_strategies import get_strategy
from ..knowledge.part_types import DrawingSpec, PartType


# ---------------------------------------------------------------------------
# Feature helpers
# ---------------------------------------------------------------------------


def _extract_features_from_spec(spec: DrawingSpec) -> set[str]:
    """Derive a set of semantic feature tags from a DrawingSpec.

    Tags come from three sources:
    - ``base_body.method``: ``"revolve"``, ``"extrude"``, etc.
    - ``base_body.bore``: adds ``"bore"`` when present.
    - ``spec.features[i]["type"]``: ``"hole_pattern"``, ``"fillet"``, etc.
    """
    features: set[str] = set()

    if spec.base_body.method:
        features.add(spec.base_body.method)

    if spec.base_body.bore is not None:
        features.add("bore")

    for feat in spec.features:
        feat_type = feat.get("type", "")
        if feat_type:
            features.add(feat_type)

    return features


def _jaccard(a: set[str], b: frozenset[str]) -> float:
    """Return the Jaccard similarity between two feature sets.

    Returns 0.0 when both sets are empty.
    """
    if not a and not b:
        return 0.0
    union_size = len(a | b)
    if union_size == 0:
        return 0.0
    return len(a & b) / union_size


# ---------------------------------------------------------------------------
# Context / Strategist
# ---------------------------------------------------------------------------


@dataclass
class ModelingContext:
    """建模上下文 — 传递给 Code Generator 的全部信息"""

    drawing_spec: DrawingSpec
    strategy: str
    examples: list[tuple[str, str]]

    def to_prompt_text(self) -> str:
        """组装为 Coder 模型的完整输入 prompt"""
        parts = [
            self.drawing_spec.to_prompt_text(),
            "",
            self.strategy,
            "",
        ]
        if self.examples:
            parts.append("## 参考代码示例")
            parts.append("")
            for desc, code in self.examples:
                parts.append(f"### {desc}")
                parts.append(f"```python\n{code}\n```")
                parts.append("")
        return "\n".join(parts)


class ModelingStrategist:
    """阶段 1.5：根据零件类型和特征选择建模策略（纯规则引擎，无 LLM）"""

    def select(
        self,
        spec: DrawingSpec,
        max_examples: int = 3,
    ) -> ModelingContext:
        """Select strategy and top-k feature-matched examples.

        Algorithm
        ---------
        1. Extract feature tags from *spec* (method, bore, feature types).
        2. Collect all unique TaggedExamples across the full knowledge base.
        3. Rank by Jaccard(spec_features, example.features), descending.
        4. Return top *max_examples* as (description, code) tuples.

        When *max_examples* is 0 or negative, returns an empty list.
        """
        strategy = get_strategy(spec.part_type)

        if max_examples <= 0:
            return ModelingContext(
                drawing_spec=spec,
                strategy=strategy,
                examples=[],
            )

        # Deduplicate examples by identity (ROTATIONAL and ROTATIONAL_STEPPED share
        # the same list object).
        seen_ids: set[int] = set()
        all_examples: list[TaggedExample] = []
        for examples in EXAMPLES_BY_TYPE.values():
            for ex in examples:
                if id(ex) not in seen_ids:
                    seen_ids.add(id(ex))
                    all_examples.append(ex)

        spec_features = _extract_features_from_spec(spec)

        # Sort by descending Jaccard similarity; stable sort preserves insertion
        # order for tied scores (type-first ordering).
        ranked = sorted(
            all_examples,
            key=lambda ex: _jaccard(spec_features, ex.features),
            reverse=True,
        )

        top = ranked[:max_examples]
        return ModelingContext(
            drawing_spec=spec,
            strategy=strategy,
            examples=[(ex.description, ex.code) for ex in top],
        )
