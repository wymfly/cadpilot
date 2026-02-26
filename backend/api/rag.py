"""RAG retrieval API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..infra.rag import RAGPipeline, embed_text_mock

router = APIRouter(prefix="/rag", tags=["rag"])

# Module-level singleton, lazily initialised on first request.
_pipeline: RAGPipeline | None = None


def _get_pipeline() -> RAGPipeline:
    """Return the shared RAGPipeline, loading knowledge base on first call."""
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        _pipeline = RAGPipeline(embed_fn=embed_text_mock)
        _pipeline.load_from_knowledge_base()
    return _pipeline


# -- response models ----------------------------------------------------------


class RAGSearchResult(BaseModel):
    """Single search result returned by the /rag/search endpoint."""

    id: str
    description: str
    code: str
    score: float
    part_type: str | None = None


# -- endpoints ----------------------------------------------------------------


@router.get("/search")
async def search_examples(
    q: str = Query(..., description="搜索文本"),
    top_k: int = Query(3, ge=1, le=10),
    part_type: str | None = Query(None),
) -> list[RAGSearchResult]:
    """Search the RAG knowledge base for similar examples."""
    pipe = _get_pipeline()
    results = pipe.search(q, top_k=top_k, part_type=part_type)
    return [
        RAGSearchResult(
            id=r.id,
            description=r.description,
            code=r.code,
            score=r.score,
            part_type=r.part_type,
        )
        for r in results
    ]


@router.get("/stats")
async def rag_stats() -> dict:
    """Return RAG pipeline statistics."""
    pipe = _get_pipeline()
    return {"total_entries": len(pipe)}
