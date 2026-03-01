"""V1 参数化模板 API — CRUD + validate。

GET    /api/v1/templates                列出所有模板（可按 part_type 过滤）
GET    /api/v1/templates/{name}         获取单个模板
POST   /api/v1/templates                创建新模板
PUT    /api/v1/templates/{name}         更新模板
DELETE /api/v1/templates/{name}         删除模板
POST   /api/v1/templates/{name}/validate  校验参数
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

import re

from backend.api.v1.errors import APIError, ErrorCode
from backend.core.template_engine import TemplateEngine
from backend.models.template import ParametricTemplate

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

router = APIRouter(prefix="/templates", tags=["templates"])

# Templates directory — overridable for testing via monkeypatch.
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "knowledge" / "templates"


def _get_engine() -> TemplateEngine:
    """Load a fresh engine from the templates directory."""
    return TemplateEngine.from_directory(_TEMPLATES_DIR)


def _require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Reject write requests when API key is configured but not provided."""
    import hmac

    from backend.config import Settings

    settings = Settings()
    if settings.api_key is not None and settings.api_key != "":
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
            raise APIError(
                status_code=401,
                code=ErrorCode.UNAUTHORIZED,
                message="Invalid or missing API key",
            )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ValidateResponse(BaseModel):
    """Result of parameter validation."""

    valid: bool
    errors: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_templates(part_type: Optional[str] = None) -> list[dict[str, Any]]:
    """列出所有模板，可按 ``part_type`` 过滤。"""
    engine = _get_engine()
    templates = engine.list_templates()
    if part_type:
        templates = [t for t in templates if t.part_type == part_type]
    return [t.model_dump() for t in templates]


@router.get("/{name}")
async def get_template(name: str) -> dict[str, Any]:
    """返回单个模板（不存在则 404）。"""
    engine = _get_engine()
    try:
        tmpl = engine.get_template(name)
    except KeyError:
        raise APIError(
            status_code=404,
            code=ErrorCode.TEMPLATE_NOT_FOUND,
            message=f"Template '{name}' not found",
        )
    return tmpl.model_dump()


@router.post("", status_code=201, dependencies=[Depends(_require_api_key)])
async def create_template(body: dict[str, Any]) -> dict[str, Any]:
    """创建新模板（名称冲突则 409）。"""
    tmpl = ParametricTemplate.model_validate(body)
    if not _SAFE_NAME_RE.match(tmpl.name):
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message="Template name must contain only alphanumeric, underscore, or hyphen characters",
        )
    path = _TEMPLATES_DIR / f"{tmpl.name}.yaml"
    if path.exists():
        raise APIError(
            status_code=409,
            code=ErrorCode.TEMPLATE_EXISTS,
            message=f"Template '{tmpl.name}' already exists",
        )
    path.write_text(tmpl.to_yaml_string(), encoding="utf-8")
    return tmpl.model_dump()


@router.put("/{name}", dependencies=[Depends(_require_api_key)])
async def update_template(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """更新已有模板（不存在则 404）。"""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        # Try glob match for templates stored with prefixed filenames.
        from glob import escape as _glob_escape

        matches = list(_TEMPLATES_DIR.glob(f"*{_glob_escape(name)}*.yaml"))
        if not matches:
            raise APIError(
                status_code=404,
                code=ErrorCode.TEMPLATE_NOT_FOUND,
                message=f"Template '{name}' not found",
            )
        path = matches[0]
    tmpl = ParametricTemplate.model_validate(body)
    path.write_text(tmpl.to_yaml_string(), encoding="utf-8")
    return tmpl.model_dump()


@router.delete("/{name}", dependencies=[Depends(_require_api_key)])
async def delete_template(name: str) -> dict[str, str]:
    """删除模板（不存在则 404）。"""
    path = _TEMPLATES_DIR / f"{name}.yaml"
    if not path.exists():
        from glob import escape as _glob_escape

        matches = list(_TEMPLATES_DIR.glob(f"*{_glob_escape(name)}*.yaml"))
        if not matches:
            raise APIError(
                status_code=404,
                code=ErrorCode.TEMPLATE_NOT_FOUND,
                message=f"Template '{name}' not found",
            )
        path = matches[0]
    path.unlink()
    return {"status": "deleted", "name": name}


@router.post("/{name}/validate")
async def validate_params(name: str, body: dict[str, Any]) -> ValidateResponse:
    """校验参数是否满足模板定义和约束。"""
    engine = _get_engine()
    try:
        errors = engine.validate(name, body)
    except KeyError:
        raise APIError(
            status_code=404,
            code=ErrorCode.TEMPLATE_NOT_FOUND,
            message=f"Template '{name}' not found",
        )
    return ValidateResponse(valid=len(errors) == 0, errors=errors)
