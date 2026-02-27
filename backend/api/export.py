"""Export endpoint: convert STEP to STL/3MF/glTF, or download raw STEP."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from backend.core.format_exporter import ExportConfig, FormatExporter

router = APIRouter()

_ALLOWED_DIR = Path("outputs").resolve()

_MEDIA_TYPES = {
    "step": "application/STEP",
    "stl": "application/sla",
    "3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
    "gltf": "model/gltf-binary",
}

_EXTENSIONS = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "gltf": ".glb"}


class ExportRequest(BaseModel):
    """Request body for the export endpoint."""

    step_path: str = ""
    job_id: str = ""
    config: ExportConfig = ExportConfig()


@router.post("/export")
async def export_model(body: ExportRequest) -> FileResponse:
    config = body.config

    if body.job_id:
        from backend.infra.outputs import get_step_path

        resolved = get_step_path(body.job_id)
        if not resolved.is_relative_to(_ALLOWED_DIR):
            raise HTTPException(
                status_code=403,
                detail="Access denied: path outside allowed directory",
            )
    elif body.step_path:
        resolved = Path(body.step_path).resolve()
        if not resolved.is_relative_to(_ALLOWED_DIR):
            raise HTTPException(
                status_code=403,
                detail="Access denied: path outside allowed directory",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Either job_id or step_path is required",
        )

    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail=f"STEP file not found: {resolved}",
        )

    # Direct STEP download — no conversion needed
    if config.format == "step":
        return FileResponse(
            path=str(resolved),
            media_type=_MEDIA_TYPES["step"],
            filename="model.step",
        )

    ext = _EXTENSIONS[config.format]
    fd, out_path = tempfile.mkstemp(suffix=ext)
    import os

    os.close(fd)

    exporter = FormatExporter()
    exporter.export(str(resolved), out_path, config)

    def _cleanup() -> None:
        Path(out_path).unlink(missing_ok=True)

    return FileResponse(
        path=out_path,
        media_type=_MEDIA_TYPES[config.format],
        filename=f"model{ext}",
        background=BackgroundTask(_cleanup),
    )
