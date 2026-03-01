"""V1 路由蓝图 — 聚合所有 /api/v1/ 子路由。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import (
    benchmark,
    events,
    export,
    health,
    jobs,
    llm_config,
    organic,
    pipeline_config,
    preview,
    print_config,
    rag,
    standards,
    templates,
)

router = APIRouter()
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(events.router)
router.include_router(preview.router)
router.include_router(pipeline_config.router)
router.include_router(rag.router)
router.include_router(export.router)
router.include_router(benchmark.router)
router.include_router(standards.router)
router.include_router(print_config.router)
router.include_router(templates.router)
router.include_router(organic.router)
router.include_router(llm_config.router)
