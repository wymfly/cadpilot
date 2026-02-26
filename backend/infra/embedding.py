"""Lightweight embedding store for vector-based example retrieval.

Uses numpy cosine similarity for in-memory search.
No database dependency -- vectors stored as numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from ..knowledge.part_types import DrawingSpec


@dataclass
class SearchResult:
    """Single search hit from the embedding store."""

    key: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class EmbeddingStore:
    """In-memory vector store with cosine similarity search.

    Vectors are L2-normalised on insertion so that dot-product equals
    cosine similarity at query time.
    """

    def __init__(self) -> None:
        self._keys: list[str] = []
        self._vectors: list[np.ndarray] = []
        self._metadata: list[dict[str, Any]] = []

    # -- mutate ---------------------------------------------------------------

    def add(
        self,
        key: str,
        vector: np.ndarray,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Add a vector with an associated key and optional metadata."""
        norm = float(np.linalg.norm(vector))
        self._keys.append(key)
        self._vectors.append(vector / (norm + 1e-10))
        self._metadata.append(metadata or {})

    # -- query ----------------------------------------------------------------

    def find_similar(
        self,
        query: np.ndarray,
        top_k: int = 5,
        filter_metadata: Optional[dict[str, Any]] = None,
    ) -> list[SearchResult]:
        """Return the *top_k* most similar vectors to *query*.

        When *filter_metadata* is provided, only entries whose metadata
        contains **all** specified key-value pairs are considered.
        """
        if not self._vectors:
            return []

        q_norm = query / (float(np.linalg.norm(query)) + 1e-10)
        matrix = np.stack(self._vectors)
        scores: np.ndarray = matrix @ q_norm

        results: list[SearchResult] = []
        for idx in np.argsort(scores)[::-1]:
            meta = self._metadata[int(idx)]
            if filter_metadata:
                if not all(meta.get(k) == v for k, v in filter_metadata.items()):
                    continue
            results.append(
                SearchResult(
                    key=self._keys[int(idx)],
                    score=float(scores[int(idx)]),
                    metadata=meta,
                )
            )
            if len(results) >= top_k:
                break
        return results

    # -- introspection --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._keys)


# ---------------------------------------------------------------------------
# Spec-to-text helper
# ---------------------------------------------------------------------------


def spec_to_embedding_text(spec: DrawingSpec) -> str:
    """Convert a *DrawingSpec* to a flat text string suitable for embedding.

    The output concatenates the part type, description, base-body method,
    and all feature types -- just enough semantic signal for a lightweight
    embedding model to capture similarity.
    """
    parts: list[str] = [
        spec.part_type.value,
        spec.description,
        spec.base_body.method,
    ]
    for feat in spec.features:
        parts.append(feat.type)
    return " ".join(parts)
