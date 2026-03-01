"""V1 路由蓝图 — 聚合所有 /api/v1/ 子路由。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import events, health, jobs, pipeline_config, preview, rag

router = APIRouter()
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(events.router)
router.include_router(preview.router)
router.include_router(pipeline_config.router)
router.include_router(rag.router)
