"""Tests for vector retrieval infrastructure (Phase 3 Task 3.7).

Validates:
- EmbeddingStore add / find_similar / __len__
- find_similar with top_k limiting
- find_similar on empty store
- Metadata filtering
- spec_to_embedding_text conversion
- ModelingStrategist Jaccard fallback (no embedding store)
- ModelingStrategist Jaccard fallback (embedding_store=None)
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.infra.embedding import EmbeddingStore, SearchResult, spec_to_embedding_text
from backend.knowledge.part_types import (
    BaseBodySpec,
    BoreSpec,
    DrawingSpec,
    Feature,
    PartType,
)
from cad3dify.v2.modeling_strategist import ModelingContext, ModelingStrategist


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _random_vec(dim: int = 64, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32)


def _make_flange_spec() -> DrawingSpec:
    """Reusable flange spec (rotational_stepped, revolve, bore, holes)."""
    return DrawingSpec(
        part_type=PartType.ROTATIONAL_STEPPED,
        description="Flange disc",
        views=["front_section", "top"],
        overall_dimensions={"max_diameter": 100, "total_height": 30},
        base_body=BaseBodySpec(
            method="revolve",
            bore=BoreSpec(diameter=10, through=True),
        ),
        features=[
            {"type": "hole_pattern", "count": 6, "diameter": 10, "pcd": 70},
            {"type": "fillet", "radius": 3},
        ],
    )


def _make_plate_spec() -> DrawingSpec:
    return DrawingSpec(
        part_type=PartType.PLATE,
        description="Mounting plate",
        views=["front", "top"],
        overall_dimensions={"length": 200, "width": 150},
        base_body=BaseBodySpec(method="extrude"),
        features=[{"type": "hole_pattern", "count": 4, "diameter": 12, "pcd": 0}],
    )


# ---------------------------------------------------------------------------
# TestEmbeddingStore
# ---------------------------------------------------------------------------


class TestEmbeddingStoreBasic:
    """Core add / find_similar / __len__ behaviour."""

    def test_add_and_find_similar(self) -> None:
        store = EmbeddingStore()
        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        store.add("a", v1)
        store.add("b", v2)

        results = store.find_similar(v1, top_k=1)
        assert len(results) == 1
        assert results[0].key == "a"
        assert results[0].score > 0.99

    def test_find_similar_returns_search_result(self) -> None:
        store = EmbeddingStore()
        store.add("x", np.array([1.0, 0.0]), metadata={"tag": "alpha"})
        results = store.find_similar(np.array([1.0, 0.0]), top_k=1)
        r = results[0]
        assert isinstance(r, SearchResult)
        assert r.key == "x"
        assert r.metadata == {"tag": "alpha"}

    def test_len(self) -> None:
        store = EmbeddingStore()
        assert len(store) == 0
        store.add("a", np.array([1.0, 0.0]))
        assert len(store) == 1
        store.add("b", np.array([0.0, 1.0]))
        assert len(store) == 2

    def test_empty_store_returns_empty_list(self) -> None:
        store = EmbeddingStore()
        results = store.find_similar(np.array([1.0, 0.0]), top_k=5)
        assert results == []


class TestEmbeddingStoreTopK:
    """Top-k limiting and ranking."""

    def test_top_k_limits_results(self) -> None:
        store = EmbeddingStore()
        dim = 8
        for i in range(10):
            store.add(f"item-{i}", _random_vec(dim, seed=i))

        results = store.find_similar(_random_vec(dim, seed=0), top_k=3)
        assert len(results) == 3

    def test_top_k_larger_than_store(self) -> None:
        store = EmbeddingStore()
        store.add("only", np.array([1.0, 0.0, 0.0]))
        results = store.find_similar(np.array([1.0, 0.0, 0.0]), top_k=10)
        assert len(results) == 1

    def test_results_sorted_by_score_desc(self) -> None:
        store = EmbeddingStore()
        store.add("exact", np.array([1.0, 0.0]))
        store.add("ortho", np.array([0.0, 1.0]))
        store.add("close", np.array([0.9, 0.1]))

        results = store.find_similar(np.array([1.0, 0.0]), top_k=3)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


class TestEmbeddingStoreFilter:
    """Metadata filtering."""

    def test_filter_metadata_includes_matching(self) -> None:
        store = EmbeddingStore()
        store.add("a", np.array([1.0, 0.0]), metadata={"type": "gear"})
        store.add("b", np.array([0.9, 0.1]), metadata={"type": "plate"})
        store.add("c", np.array([0.8, 0.2]), metadata={"type": "gear"})

        results = store.find_similar(
            np.array([1.0, 0.0]),
            top_k=5,
            filter_metadata={"type": "gear"},
        )
        assert len(results) == 2
        assert all(r.metadata["type"] == "gear" for r in results)

    def test_filter_metadata_no_match(self) -> None:
        store = EmbeddingStore()
        store.add("a", np.array([1.0, 0.0]), metadata={"type": "gear"})
        results = store.find_similar(
            np.array([1.0, 0.0]),
            top_k=5,
            filter_metadata={"type": "housing"},
        )
        assert results == []

    def test_filter_metadata_multiple_keys(self) -> None:
        store = EmbeddingStore()
        store.add("a", np.array([1.0, 0.0]), metadata={"type": "gear", "size": "L"})
        store.add("b", np.array([0.9, 0.1]), metadata={"type": "gear", "size": "S"})

        results = store.find_similar(
            np.array([1.0, 0.0]),
            top_k=5,
            filter_metadata={"type": "gear", "size": "L"},
        )
        assert len(results) == 1
        assert results[0].key == "a"


# ---------------------------------------------------------------------------
# TestSpecToEmbeddingText
# ---------------------------------------------------------------------------


class TestSpecToEmbeddingText:
    def test_basic_conversion(self) -> None:
        spec = _make_flange_spec()
        text = spec_to_embedding_text(spec)
        assert "rotational_stepped" in text
        assert "revolve" in text
        assert "hole_pattern" in text
        assert "fillet" in text
        assert "Flange disc" in text

    def test_plate_conversion(self) -> None:
        spec = _make_plate_spec()
        text = spec_to_embedding_text(spec)
        assert "plate" in text
        assert "extrude" in text
        assert "hole_pattern" in text

    def test_returns_string(self) -> None:
        spec = _make_flange_spec()
        assert isinstance(spec_to_embedding_text(spec), str)

    def test_no_features(self) -> None:
        spec = DrawingSpec(
            part_type=PartType.GENERAL,
            description="simple block",
            base_body=BaseBodySpec(method="extrude"),
            features=[],
        )
        text = spec_to_embedding_text(spec)
        assert "general" in text
        assert "extrude" in text


# ---------------------------------------------------------------------------
# TestModelingStrategistFallback
# ---------------------------------------------------------------------------


class TestModelingStrategistJaccardFallback:
    """ModelingStrategist with no embedding store uses Jaccard."""

    def test_default_no_store(self) -> None:
        """Default construction (no args) uses Jaccard."""
        strategist = ModelingStrategist()
        context = strategist.select(_make_flange_spec())
        assert isinstance(context, ModelingContext)
        assert len(context.examples) > 0

    def test_explicit_none_store(self) -> None:
        """embedding_store=None uses Jaccard."""
        strategist = ModelingStrategist(embedding_store=None)
        context = strategist.select(_make_flange_spec())
        assert isinstance(context, ModelingContext)
        assert len(context.examples) > 0

    def test_empty_store_falls_back(self) -> None:
        """An empty EmbeddingStore triggers Jaccard fallback."""
        store = EmbeddingStore()
        assert len(store) == 0
        strategist = ModelingStrategist(embedding_store=store)
        context = strategist.select(_make_flange_spec())
        assert isinstance(context, ModelingContext)
        assert len(context.examples) > 0

    def test_results_unchanged_from_pure_jaccard(self) -> None:
        """Jaccard path produces identical results whether store is absent or empty."""
        spec = _make_flange_spec()
        ctx_no_store = ModelingStrategist().select(spec, max_examples=3)
        ctx_empty = ModelingStrategist(embedding_store=EmbeddingStore()).select(
            spec, max_examples=3
        )
        # Same examples in same order.
        assert ctx_no_store.examples == ctx_empty.examples
        assert ctx_no_store.strategy == ctx_empty.strategy

    def test_max_examples_zero(self) -> None:
        strategist = ModelingStrategist()
        context = strategist.select(_make_flange_spec(), max_examples=0)
        assert context.examples == []


# ---------------------------------------------------------------------------
# TestSearchResultDataclass
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_defaults(self) -> None:
        r = SearchResult(key="k", score=0.9)
        assert r.key == "k"
        assert r.score == 0.9
        assert r.metadata == {}

    def test_with_metadata(self) -> None:
        r = SearchResult(key="k", score=0.5, metadata={"a": 1})
        assert r.metadata == {"a": 1}
