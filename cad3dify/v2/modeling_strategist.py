"""Modeling strategist: selects building strategy and few-shot examples.

Feature-based example selection uses Jaccard similarity between the features
extracted from a DrawingSpec and the ``features`` frozenset of each TaggedExample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..knowledge.examples import EXAMPLES_BY_TYPE, TaggedExample, get_tagged_examples
from ..knowledge.modeling_strategies import get_strategy
from ..knowledge.part_types import DrawingSpec, PartType

if TYPE_CHECKING:
    from ..infra.embedding import EmbeddingStore


# ---------------------------------------------------------------------------
# Feature helpers
# ---------------------------------------------------------------------------


def _extract_features_from_spec(spec: DrawingSpec) -> set[str]:
    """Derive a set of semantic feature tags from a DrawingSpec.

    Tags come from three sources:
    - ``base_body.method``: ``"revolve"``, ``"extrude"``, etc.
    - ``base_body.bore``: adds ``"bore"`` when present.
    - ``spec.features[i].type``: ``"hole_pattern"``, ``"fillet"``, etc.
    """
    features: set[str] = set()

    if spec.base_body.method:
        features.add(spec.base_body.method)

    if spec.base_body.bore is not None:
        features.add("bore")

    for feat in spec.features:
        if feat.type:
            features.add(feat.type)

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
    """阶段 1.5：根据零件类型和特征选择建模策略（纯规则引擎，无 LLM）

    Optionally accepts an :class:`EmbeddingStore` for vector-based example
    retrieval.  When the store is provided **and** non-empty the strategist
    attempts vector search first; on failure (or when no store is given) it
    falls back to the original Jaccard-similarity algorithm.
    """

    def __init__(
        self,
        embedding_store: EmbeddingStore | None = None,
    ) -> None:
        self._embedding_store = embedding_store

    def select(
        self,
        spec: DrawingSpec,
        max_examples: int = 3,
    ) -> ModelingContext:
        """Select strategy and top-k feature-matched examples.

        When an *embedding_store* is available, vector retrieval is attempted
        first.  If it yields results they are used; otherwise the method falls
        back to Jaccard-based ranking.

        When *max_examples* is 0 or negative, returns an empty list.
        """
        strategy = get_strategy(spec.part_type)

        if max_examples <= 0:
            return ModelingContext(
                drawing_spec=spec,
                strategy=strategy,
                examples=[],
            )

        # Try legacy embedding store (backward compat).
        if self._embedding_store is not None and len(self._embedding_store) > 0:
            examples = self._select_by_vector(spec, max_examples)
            if examples:
                return ModelingContext(
                    drawing_spec=spec,
                    strategy=strategy,
                    examples=examples,
                )

        # Fallback: Jaccard similarity.
        return self._select_by_jaccard(spec, max_examples, strategy)

    # -- private: Jaccard path ------------------------------------------------

    def _select_by_jaccard(
        self,
        spec: DrawingSpec,
        max_examples: int,
        strategy: str,
    ) -> ModelingContext:
        """Original Jaccard-similarity example selection."""
        # Deduplicate examples by identity (ROTATIONAL and ROTATIONAL_STEPPED
        # share the same list object).
        seen_ids: set[int] = set()
        all_examples: list[TaggedExample] = []
        for examples in EXAMPLES_BY_TYPE.values():
            for ex in examples:
                if id(ex) not in seen_ids:
                    seen_ids.add(id(ex))
                    all_examples.append(ex)

        spec_features = _extract_features_from_spec(spec)

        # IDs of examples that belong to the requested part type (used as
        # tiebreaker: prefer same-type examples when Jaccard scores are equal).
        spec_type_ids: set[int] = {
            id(ex) for ex in EXAMPLES_BY_TYPE.get(spec.part_type, [])
        }

        # Primary sort: descending Jaccard similarity.
        # Secondary sort: same-type examples rank before others (0 < 1).
        ranked = sorted(
            all_examples,
            key=lambda ex: (
                -_jaccard(spec_features, ex.features),
                0 if id(ex) in spec_type_ids else 1,
            ),
        )

        top = ranked[:max_examples]
        return ModelingContext(
            drawing_spec=spec,
            strategy=strategy,
            examples=[(ex.description, ex.code) for ex in top],
        )

    # -- private: vector path -------------------------------------------------

    def _select_by_vector(
        self,
        spec: DrawingSpec,
        max_examples: int,
    ) -> list[tuple[str, str]]:
        """Attempt vector-based example retrieval.

        Returns an empty list when no embedding model is available or when
        the store yields no results -- callers should fall back to Jaccard.

        .. note::

           This is a **placeholder**: a real embedding model is needed to
           produce query vectors.  The infrastructure (``EmbeddingStore``,
           ``spec_to_embedding_text``) is fully functional and tested.
        """
        # Placeholder -- return empty to trigger Jaccard fallback.
        # When an embedding model is integrated, this method will:
        #   1. Call spec_to_embedding_text(spec) to get query text.
        #   2. Embed the text via the model.
        #   3. Call self._embedding_store.find_similar(query_vec, top_k=max_examples).
        #   4. Map SearchResult keys back to (description, code) tuples.
        return []
