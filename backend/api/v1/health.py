"""健康检查端点 — GET /api/v1/health。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "3.0.0"}
