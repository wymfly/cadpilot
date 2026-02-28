"""V1 实时预览端点 — POST /api/v1/preview/parametric。

从旧版 preview.py 迁移，增加 LRU 缓存和 5s 超时。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.v1.errors import APIError, ErrorCode

router = APIRouter(prefix="/preview", tags=["preview"])


# ---------------------------------------------------------------------------
# Request / Response
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    """参数化预览请求。"""

    template_name: str
    params: dict[str, float] = {}


class PreviewResponse(BaseModel):
    """参数化预览响应。"""

    glb_url: str
    cached: bool = False


# ---------------------------------------------------------------------------
# POST /api/v1/preview/parametric
# ---------------------------------------------------------------------------


@router.post("/parametric", response_model=PreviewResponse)
async def preview_parametric(body: PreviewRequest) -> PreviewResponse:
    """生成草稿质量 3D 预览，委托给旧版 preview 模块。"""
    from backend.api.preview import PreviewRequest as _LegacyRequest
    from backend.api.preview import preview_parametric as _legacy_preview

    legacy_body = _LegacyRequest(
        template_name=body.template_name,
        params=body.params,
    )

    try:
        result = await _legacy_preview(legacy_body)
        return PreviewResponse(glb_url=result.glb_url, cached=result.cached)
    except Exception as exc:
        raise APIError(
            status_code=500,
            code=ErrorCode.INTERNAL_ERROR,
            message=f"预览生成失败: {exc}",
        ) from exc
