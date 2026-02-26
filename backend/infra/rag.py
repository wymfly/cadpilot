"""RAG pipeline: loads examples into EmbeddingStore, provides retrieval API.

Uses dependency-injected embedding function for testability.
Real embedding model (sentence-transformers) replaces embed_text_mock in prod.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

from .embedding import EmbeddingStore

# Type alias for embedding function: text -> vector
EmbedFn = Callable[[str], np.ndarray]

_MOCK_DIM = 64


def embed_text_mock(text: str) -> np.ndarray:
    """Deterministic mock embedding: SHA256 hash -> float64 vector.

    Produces a 64-dimensional vector from the SHA256 digest.
    Same input always produces the same output (deterministic).
    """
    digest = hashlib.sha256(text.encode()).digest()
    # SHA256 produces 32 bytes; interpret as uint8 array
    arr = np.frombuffer(digest, dtype=np.uint8).astype(np.float64)
    # Pad to _MOCK_DIM if needed (32 < 64)
    if len(arr) < _MOCK_DIM:
        # Double the digest by hashing the hash for more bytes
        digest2 = hashlib.sha256(digest).digest()
        arr2 = np.frombuffer(digest2, dtype=np.uint8).astype(np.float64)
        arr = np.concatenate([arr, arr2])
    return arr[:_MOCK_DIM]


@dataclass
class RAGEntry:
    """Single entry in the RAG knowledge base."""

    id: str
    description: str
    code: str
    tags: set[str] = field(default_factory=set)
    part_type: Optional[str] = None

    def to_embedding_text(self) -> str:
        """Convert entry to text suitable for embedding."""
        parts = [self.description]
        if self.tags:
            parts.extend(sorted(self.tags))
        if self.part_type:
            parts.append(self.part_type)
        return " ".join(parts)


@dataclass
class RAGResult:
    """Search result from RAG pipeline."""

    id: str
    description: str
    code: str
    score: float
    part_type: Optional[str] = None


class RAGPipeline:
    """RAG pipeline wrapping EmbeddingStore with knowledge-base loading.

    Parameters
    ----------
    embed_fn:
        Callable that converts text to a numpy vector.
        Defaults to ``embed_text_mock`` for testing.
    """

    def __init__(self, embed_fn: EmbedFn = embed_text_mock) -> None:
        self._embed_fn = embed_fn
        self._store = EmbeddingStore()
        self._entries: dict[str, RAGEntry] = {}

    # -- mutate ---------------------------------------------------------------

    def add(self, entry: RAGEntry) -> None:
        """Add a RAGEntry to the store, embedding its text representation.

        If an entry with the same ID already exists, it is overwritten
        and a warning is logged.
        """
        if entry.id in self._entries:
            logger.warning("Overwriting existing RAG entry: %s", entry.id)
        vec = self._embed_fn(entry.to_embedding_text())
        self._store.add(
            key=entry.id,
            vector=vec,
            metadata={
                "part_type": entry.part_type or "",
                "description": entry.description,
                "code": entry.code,
            },
        )
        self._entries[entry.id] = entry

    # -- query ----------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 3,
        part_type: Optional[str] = None,
    ) -> list[RAGResult]:
        """Search for similar entries by query text.

        Parameters
        ----------
        query:
            Natural-language search text.
        top_k:
            Maximum number of results to return.
        part_type:
            Optional filter to restrict results to a specific part type.
        """
        if len(self._store) == 0:
            return []
        q_vec = self._embed_fn(query)
        filter_meta = {"part_type": part_type} if part_type else None
        hits = self._store.find_similar(
            q_vec, top_k=top_k, filter_metadata=filter_meta
        )
        return [
            RAGResult(
                id=h.key,
                description=h.metadata.get("description", ""),
                code=h.metadata.get("code", ""),
                score=h.score,
                part_type=h.metadata.get("part_type") or None,
            )
            for h in hits
        ]

    # -- bulk load ------------------------------------------------------------

    def load_from_knowledge_base(self) -> int:
        """Load all TaggedExample from backend.knowledge.examples into store.

        De-duplicates by object identity (some examples are shared across
        part types, e.g. ROTATIONAL and ROTATIONAL_STEPPED).

        Returns the number of unique entries added.
        """
        from ..knowledge.examples import EXAMPLES_BY_TYPE

        count = 0
        seen: set[int] = set()
        for part_type, examples in EXAMPLES_BY_TYPE.items():
            for idx, ex in enumerate(examples):
                if id(ex) in seen:
                    continue
                seen.add(id(ex))
                # TaggedExample has: description, code, features (frozenset)
                # No 'name' attr, so generate a stable id from part_type + index
                entry_id = f"kb_{part_type.value}_{idx}"
                entry = RAGEntry(
                    id=entry_id,
                    description=ex.description,
                    code=ex.code,
                    tags=set(ex.features),
                    part_type=part_type.value,
                )
                self.add(entry)
                count += 1
        return count

    # -- introspection --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._store)
