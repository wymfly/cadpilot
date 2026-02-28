"""Parametric preview API — fast draft-quality 3D preview.

POST /preview/parametric → render template → CadQuery → STEP → GLB
with caching and 5s hard timeout.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.infra.outputs import ensure_job_dir, get_model_url

router = APIRouter(prefix="/preview", tags=["preview"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    """Request body for parametric preview."""

    template_name: str
    params: dict[str, float] = {}


class PreviewResponse(BaseModel):
    """Response body for parametric preview."""

    glb_url: str
    cached: bool = False


# ---------------------------------------------------------------------------
# In-memory preview cache
# ---------------------------------------------------------------------------

_preview_cache: dict[str, str] = {}
_PREVIEW_CACHE_MAX_SIZE = 100


def invalidate_preview_cache(template_name: str | None = None) -> int:
    """Invalidate preview cache entries. Returns count of removed entries.

    Args:
        template_name: If provided, only invalidate entries for this template.
                       If None, clear entire cache.
    """
    if template_name is None:
        count = len(_preview_cache)
        _preview_cache.clear()
        return count
    keys_to_remove = [
        k for k in _preview_cache if k.startswith(f"{template_name}:")
    ]
    for k in keys_to_remove:
        del _preview_cache[k]
    return len(keys_to_remove)


# ---------------------------------------------------------------------------
# Template + execution helpers (module-level for mockability)
# ---------------------------------------------------------------------------


def _get_template(template_name: str) -> Any:
    """Load a parametric template by name. Returns None if not found."""
    try:
        from backend.core.template_engine import TemplateEngine

        templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(templates_dir)
        return engine.get_template(template_name)
    except (KeyError, Exception):
        return None


def _validate_template_params(template: Any, params: dict[str, float]) -> list[str]:
    """Validate params against template constraints."""
    return template.validate_params(params)


def _render_preview(template_name: str, params: dict[str, float]) -> str:
    """Render template → CadQuery execute → STEP → GLB.

    Uses draft-quality tessellation (higher deflection = fewer faces).
    Returns the GLB file path.
    """
    from backend.core.format_exporter import ExportConfig, FormatExporter
    from backend.core.template_engine import TemplateEngine
    from backend.infra.sandbox import SafeExecutor

    templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
    engine = TemplateEngine.from_directory(templates_dir)

    # Create a temporary directory for preview output
    preview_dir = Path(tempfile.mkdtemp(prefix="preview_"))
    step_path = str(preview_dir / "preview.step")
    glb_path = str(preview_dir / "preview.glb")

    try:
        # Render CadQuery code from template
        code = engine.render(template_name, params, output_filename=step_path)

        # Execute in sandbox
        executor = SafeExecutor(timeout_s=5)
        result = executor.execute(code)

        if not result.success:
            raise RuntimeError(f"CadQuery execution failed: {result.stderr}")
        if not Path(step_path).exists():
            raise RuntimeError("CadQuery did not produce a STEP file")

        # Convert STEP → GLB with draft quality (higher deflection = fewer faces)
        exporter = FormatExporter()
        draft_config = ExportConfig(
            format="gltf",
            linear_deflection=0.3,   # ~70% fewer faces than default 0.1
            angular_deflection=1.0,
        )
        exporter.export(step_path, glb_path, draft_config)

        return glb_path
    except Exception:
        # Clean up temp directory on failure to prevent leaks
        shutil.rmtree(preview_dir, ignore_errors=True)
        raise


# ---------------------------------------------------------------------------
# POST /preview/parametric
# ---------------------------------------------------------------------------


@router.post("/parametric")
async def preview_parametric(body: PreviewRequest) -> PreviewResponse:
    """Generate a draft-quality 3D preview from a parametric template."""
    # 1. Load template
    template = _get_template(body.template_name)
    if template is None:
        raise HTTPException(
            status_code=404,
            detail=f"Template '{body.template_name}' not found",
        )

    # 2. Validate params
    violations = _validate_template_params(template, body.params)
    if violations:
        raise HTTPException(status_code=422, detail=violations)

    # 3. Check cache
    params_hash = hashlib.md5(
        json.dumps(body.params, sort_keys=True).encode(),
    ).hexdigest()
    cache_key = f"{body.template_name}:{params_hash}"
    if cache_key in _preview_cache:
        return PreviewResponse(
            glb_url=_preview_cache[cache_key], cached=True,
        )

    # 4. Render + execute with 5s timeout
    try:
        glb_path = await asyncio.wait_for(
            asyncio.to_thread(_render_preview, body.template_name, body.params),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=408, detail="预览超时，请直接生成完整模型",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # 5. Move GLB to outputs directory and return URL
    preview_job_id = f"preview-{body.template_name[:12]}-{params_hash[:8]}"
    out_dir = ensure_job_dir(preview_job_id)
    final_glb = str(out_dir / "model.glb")
    Path(final_glb).parent.mkdir(parents=True, exist_ok=True)
    shutil.move(glb_path, final_glb)

    # Clean up temp directory (GLB already moved to outputs)
    preview_dir = Path(glb_path).parent
    if preview_dir.name.startswith("preview_"):
        shutil.rmtree(preview_dir, ignore_errors=True)

    glb_url = get_model_url(preview_job_id, "glb")

    # Evict oldest entries if cache exceeds max size
    if len(_preview_cache) >= _PREVIEW_CACHE_MAX_SIZE:
        oldest_key = next(iter(_preview_cache))
        del _preview_cache[oldest_key]
    _preview_cache[cache_key] = glb_url

    return PreviewResponse(glb_url=glb_url)
