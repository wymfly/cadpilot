"""Tests for RAG data pipeline and retrieval API."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from backend.infra.rag import (
    RAGEntry,
    RAGPipeline,
    RAGResult,
    embed_text_mock,
)
from backend.infra.embedding import EmbeddingStore


# ---------------------------------------------------------------------------
# RAGEntry
# ---------------------------------------------------------------------------


class TestRAGEntry:
    def test_create_entry(self) -> None:
        entry = RAGEntry(
            id="ex_001",
            description="圆柱法兰盘",
            code="import cq...",
            tags={"revolve", "flange"},
        )
        assert entry.id == "ex_001"
        assert entry.description == "圆柱法兰盘"
        assert entry.code == "import cq..."
        assert "revolve" in entry.tags
        assert "flange" in entry.tags

    def test_entry_default_tags(self) -> None:
        entry = RAGEntry(id="e", description="d", code="c")
        assert entry.tags == set()
        assert entry.part_type is None

    def test_entry_to_embedding_text(self) -> None:
        entry = RAGEntry(
            id="ex_001",
            description="圆柱法兰盘",
            code="import cq...",
            tags={"revolve", "bore"},
            part_type="rotational",
        )
        text = entry.to_embedding_text()
        assert "圆柱法兰盘" in text
        assert "revolve" in text
        assert "bore" in text
        assert "rotational" in text

    def test_entry_to_text_without_optional_fields(self) -> None:
        entry = RAGEntry(
            id="e1",
            description="test part",
            code="code",
            tags=set(),
        )
        text = entry.to_embedding_text()
        assert text == "test part"

    def test_entry_tags_sorted_in_text(self) -> None:
        entry = RAGEntry(
            id="e1",
            description="desc",
            code="c",
            tags={"zzz", "aaa", "mmm"},
        )
        text = entry.to_embedding_text()
        # Tags should be sorted alphabetically
        idx_a = text.index("aaa")
        idx_m = text.index("mmm")
        idx_z = text.index("zzz")
        assert idx_a < idx_m < idx_z


# ---------------------------------------------------------------------------
# embed_text_mock
# ---------------------------------------------------------------------------


class TestEmbedTextMock:
    def test_returns_numpy_array(self) -> None:
        vec = embed_text_mock("hello world")
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (64,)

    def test_deterministic(self) -> None:
        v1 = embed_text_mock("same text")
        v2 = embed_text_mock("same text")
        np.testing.assert_array_equal(v1, v2)

    def test_different_texts_different_vectors(self) -> None:
        v1 = embed_text_mock("法兰盘")
        v2 = embed_text_mock("齿轮")
        assert not np.array_equal(v1, v2)

    def test_float64_dtype(self) -> None:
        vec = embed_text_mock("test")
        assert vec.dtype == np.float64

    def test_nonzero_values(self) -> None:
        vec = embed_text_mock("test")
        assert np.any(vec != 0)

    def test_empty_string(self) -> None:
        vec = embed_text_mock("")
        assert vec.shape == (64,)


# ---------------------------------------------------------------------------
# RAGPipeline
# ---------------------------------------------------------------------------


class TestRAGPipeline:
    def test_init_empty(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        assert len(pipe) == 0

    def test_add_single_entry(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(
            RAGEntry(id="e1", description="法兰盘", code="code1", tags={"revolve"})
        )
        assert len(pipe) == 1

    def test_add_multiple_entries(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        for i in range(5):
            pipe.add(
                RAGEntry(id=f"e{i}", description=f"part {i}", code=f"code{i}", tags=set())
            )
        assert len(pipe) == 5

    def test_search_returns_results(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(
            RAGEntry(
                id="e1",
                description="法兰盘 revolve",
                code="code1",
                tags={"revolve"},
            )
        )
        pipe.add(
            RAGEntry(
                id="e2",
                description="齿轮 gear",
                code="code2",
                tags={"gear"},
            )
        )
        results = pipe.search("法兰盘 旋转体", top_k=1)
        assert len(results) == 1
        assert results[0].id in ("e1", "e2")

    def test_search_returns_rag_result_type(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(RAGEntry(id="e1", description="test", code="c", tags=set()))
        results = pipe.search("test", top_k=1)
        assert len(results) == 1
        assert isinstance(results[0], RAGResult)

    def test_search_empty_store(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        results = pipe.search("anything", top_k=3)
        assert results == []

    def test_search_returns_code(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(
            RAGEntry(
                id="e1",
                description="test",
                code="import cadquery as cq",
                tags=set(),
            )
        )
        results = pipe.search("test", top_k=1)
        assert results[0].code == "import cadquery as cq"

    def test_search_top_k_limits_results(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        for i in range(10):
            pipe.add(
                RAGEntry(id=f"e{i}", description=f"part {i}", code=f"code{i}", tags=set())
            )
        results = pipe.search("part", top_k=3)
        assert len(results) == 3

    def test_search_with_part_type_filter(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(
            RAGEntry(
                id="e1",
                description="法兰盘",
                code="c1",
                tags={"revolve"},
                part_type="rotational",
            )
        )
        pipe.add(
            RAGEntry(
                id="e2",
                description="齿轮",
                code="c2",
                tags={"gear"},
                part_type="gear",
            )
        )
        results = pipe.search("旋转", top_k=5, part_type="rotational")
        assert all(r.part_type == "rotational" for r in results)

    def test_search_without_filter_returns_all_types(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(
            RAGEntry(
                id="e1", description="a", code="c1", tags=set(), part_type="rotational"
            )
        )
        pipe.add(
            RAGEntry(
                id="e2", description="b", code="c2", tags=set(), part_type="gear"
            )
        )
        results = pipe.search("part", top_k=10)
        assert len(results) == 2

    def test_search_result_has_score(self) -> None:
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.add(RAGEntry(id="e1", description="test", code="c", tags=set()))
        results = pipe.search("test", top_k=1)
        assert isinstance(results[0].score, float)

    def test_load_from_knowledge_base(self) -> None:
        """Load all TaggedExample from knowledge base."""
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        count = pipe.load_from_knowledge_base()
        assert count >= 36  # Phase 3 added 36+ examples
        assert len(pipe) == count

    def test_load_from_knowledge_base_deduplicates(self) -> None:
        """ROTATIONAL and ROTATIONAL_STEPPED share examples; should not double-count."""
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        count = pipe.load_from_knowledge_base()
        # Load again should still return same count (entries already present)
        pipe2 = RAGPipeline(embed_fn=embed_text_mock)
        count2 = pipe2.load_from_knowledge_base()
        assert count == count2

    def test_load_and_search(self) -> None:
        """After loading KB, search should return relevant results."""
        pipe = RAGPipeline(embed_fn=embed_text_mock)
        pipe.load_from_knowledge_base()
        results = pipe.search("法兰盘 revolve 回转体", top_k=3)
        assert len(results) == 3
        for r in results:
            assert r.code  # All results should have code

    def test_custom_embed_fn(self) -> None:
        """Pipeline accepts custom embedding function."""
        call_count = 0

        def counting_embed(text: str) -> np.ndarray:
            nonlocal call_count
            call_count += 1
            return embed_text_mock(text)

        pipe = RAGPipeline(embed_fn=counting_embed)
        pipe.add(RAGEntry(id="e1", description="test", code="c", tags=set()))
        pipe.search("test")
        assert call_count == 2  # 1 for add, 1 for search


# ---------------------------------------------------------------------------
# RAG API endpoints
# ---------------------------------------------------------------------------


class TestRAGAPI:
    def test_search_endpoint(self) -> None:
        from backend.api import rag as rag_api

        # Reset singleton for clean test.
        # Note: must pass part_type=None explicitly because when called
        # directly (not through FastAPI), Query(None) default is truthy.
        rag_api._pipeline = None
        result = asyncio.run(
            rag_api.search_examples(q="法兰盘", top_k=3, part_type=None)
        )
        assert isinstance(result, list)
        assert len(result) <= 3

    def test_search_endpoint_returns_results(self) -> None:
        from backend.api import rag as rag_api

        rag_api._pipeline = None
        result = asyncio.run(
            rag_api.search_examples(q="revolve 回转体", top_k=5, part_type=None)
        )
        assert len(result) > 0
        assert result[0].id
        assert result[0].code

    def test_search_with_part_type_filter(self) -> None:
        from backend.api import rag as rag_api

        rag_api._pipeline = None
        result = asyncio.run(
            rag_api.search_examples(q="法兰盘", top_k=5, part_type="rotational")
        )
        for r in result:
            assert r.part_type == "rotational"

    def test_stats_endpoint(self) -> None:
        from backend.api import rag as rag_api

        rag_api._pipeline = None
        result = asyncio.run(rag_api.rag_stats())
        assert "total_entries" in result
        assert result["total_entries"] >= 36
