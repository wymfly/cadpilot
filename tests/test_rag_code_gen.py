"""Tests for RAG-enhanced code generation via ModelingStrategist.

Verifies that ModelingStrategist can use RAGPipeline for example retrieval,
falling back to Jaccard similarity when RAG is unavailable or empty.
"""

from __future__ import annotations

import pytest

from backend.core.modeling_strategist import ModelingContext, ModelingStrategist
from backend.infra.embedding import EmbeddingStore
from backend.infra.rag import RAGEntry, RAGPipeline, embed_text_mock
from backend.knowledge.part_types import BaseBodySpec, DrawingSpec, PartType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(part_type: str = "rotational") -> DrawingSpec:
    return DrawingSpec(
        part_type=part_type,
        description="测试法兰盘",
        overall_dimensions={"diameter": 100},
        base_body=BaseBodySpec(method="revolve"),
        features=[],
    )


def _make_rag_pipeline_with_entries(n: int = 3) -> RAGPipeline:
    """Create a RAGPipeline preloaded with *n* dummy entries."""
    pipe = RAGPipeline(embed_fn=embed_text_mock)
    for i in range(n):
        pipe.add(
            RAGEntry(
                id=f"rag_{i}",
                description=f"RAG 示例 {i}",
                code=f"import cadquery as cq  # rag example {i}",
                tags={"revolve", "bore"},
                part_type="rotational",
            )
        )
    return pipe


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRAGCodeGen:
    def test_rag_pipeline_provides_examples(self) -> None:
        """When RAG has entries, ModelingStrategist uses them."""
        rag = _make_rag_pipeline_with_entries(3)
        strategist = ModelingStrategist(rag_pipeline=rag)
        ctx = strategist.select(_make_spec(), max_examples=2)

        assert len(ctx.examples) == 2
        # All returned examples come from RAG (descriptions start with "RAG")
        for desc, code in ctx.examples:
            assert "RAG" in desc
            assert "rag example" in code

    def test_empty_rag_falls_back_to_jaccard(self) -> None:
        """Empty RAG pipeline → falls back to Jaccard examples."""
        rag = RAGPipeline(embed_fn=embed_text_mock)  # empty
        assert len(rag) == 0
        strategist = ModelingStrategist(rag_pipeline=rag)
        ctx = strategist.select(_make_spec(), max_examples=3)

        # Should still get examples from Jaccard fallback
        assert len(ctx.examples) > 0
        # Jaccard examples should NOT contain "RAG" marker
        for desc, _code in ctx.examples:
            assert "RAG" not in desc

    def test_no_rag_uses_jaccard(self) -> None:
        """No RAG pipeline at all → Jaccard only (backward compat)."""
        strategist = ModelingStrategist()
        ctx = strategist.select(_make_spec(), max_examples=3)

        assert isinstance(ctx, ModelingContext)
        assert len(ctx.examples) > 0

    def test_rag_results_in_prompt_text(self) -> None:
        """RAG examples appear in to_prompt_text() output."""
        rag = _make_rag_pipeline_with_entries(2)
        strategist = ModelingStrategist(rag_pipeline=rag)
        ctx = strategist.select(_make_spec(), max_examples=2)

        prompt = ctx.to_prompt_text()
        assert "## 参考代码示例" in prompt
        assert "RAG 示例" in prompt
        assert "rag example" in prompt

    def test_rag_loaded_from_kb(self) -> None:
        """RAGPipeline.load_from_knowledge_base() + select produces results."""
        rag = RAGPipeline(embed_fn=embed_text_mock)
        count = rag.load_from_knowledge_base()
        assert count > 0

        strategist = ModelingStrategist(rag_pipeline=rag)
        ctx = strategist.select(_make_spec(), max_examples=3)

        assert len(ctx.examples) == 3
        for desc, code in ctx.examples:
            assert desc  # non-empty description
            assert code  # non-empty code

    def test_backward_compat_embedding_store(self) -> None:
        """Old embedding_store param still accepted (returns [] → Jaccard)."""
        es = EmbeddingStore()
        strategist = ModelingStrategist(embedding_store=es)
        ctx = strategist.select(_make_spec(), max_examples=3)

        # embedding_store is empty, _select_by_vector returns [],
        # so falls back to Jaccard
        assert isinstance(ctx, ModelingContext)
        assert len(ctx.examples) > 0

    def test_rag_takes_priority_over_embedding_store(self) -> None:
        """When both RAG and embedding_store are provided, RAG wins."""
        rag = _make_rag_pipeline_with_entries(3)
        es = EmbeddingStore()  # empty — but shouldn't matter

        strategist = ModelingStrategist(
            embedding_store=es,
            rag_pipeline=rag,
        )
        ctx = strategist.select(_make_spec(), max_examples=2)

        # RAG examples should be used, not Jaccard or embedding_store
        assert len(ctx.examples) == 2
        for desc, _code in ctx.examples:
            assert "RAG" in desc

    def test_rag_exception_falls_back_to_jaccard(self) -> None:
        """When RAG search raises an exception, gracefully fall back to Jaccard."""

        class BrokenRAG(RAGPipeline):
            def search(self, *args, **kwargs):
                raise RuntimeError("embedding model unavailable")

        rag = BrokenRAG(embed_fn=embed_text_mock)
        # Add an entry so len(rag) > 0 triggers the RAG path
        rag.add(
            RAGEntry(
                id="e1", description="dummy", code="code", tags=set()
            )
        )
        strategist = ModelingStrategist(rag_pipeline=rag)
        ctx = strategist.select(_make_spec(), max_examples=3)

        # Should fall back to Jaccard despite RAG failure
        assert isinstance(ctx, ModelingContext)
        assert len(ctx.examples) > 0
        for desc, _code in ctx.examples:
            assert "RAG" not in desc  # Jaccard examples, not RAG
