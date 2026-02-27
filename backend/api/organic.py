"""Organic generation API endpoints.

All endpoints are feature-gated: ORGANIC_ENABLED must be true.
Heavy dependencies (manifold3d, pymeshlab) are lazy-loaded inside handlers.
SSE events follow standard envelope: {job_id, status, message, progress}.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from backend.config import Settings
from backend.models.organic import OrganicGenerateRequest, OrganicJobResult
from backend.models.organic_job import (
    OrganicJobStatus,
    create_organic_job,
    get_organic_job,
    update_organic_job,
)

router = APIRouter()

_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MIME_TO_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _ext_from_mime(content_type: str | None) -> str:
    """Derive file extension from MIME type. Falls back to '.png'."""
    return _MIME_TO_EXT.get(content_type or "", ".png")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_settings() -> Settings:
    return Settings()


def _require_organic_enabled(settings: Settings = Depends(_get_settings)) -> Settings:
    """Feature gate: raise 503 if organic engine is disabled."""
    if not settings.organic_enabled:
        raise HTTPException(
            status_code=503,
            detail="Organic engine is disabled. Set ORGANIC_ENABLED=true to enable.",
        )
    return settings


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse_event(
    job_id: str,
    status: str,
    message: str,
    progress: float,
    **extra: Any,
) -> dict[str, str]:
    """Create a standard SSE envelope."""
    data = {
        "job_id": job_id,
        "status": status,
        "message": message,
        "progress": progress,
        **extra,
    }
    return {"event": "organic", "data": json.dumps(data, ensure_ascii=False)}


# ---------------------------------------------------------------------------
# Text-mode SSE endpoint
# ---------------------------------------------------------------------------


@router.post("/generate/organic")
async def generate_organic(
    request: OrganicGenerateRequest,
    settings: Settings = Depends(_require_organic_enabled),
) -> EventSourceResponse:
    """Generate organic 3D model from text and/or image via SSE stream."""
    if not request.prompt.strip() and not request.reference_image:
        raise HTTPException(
            status_code=422,
            detail="At least one of prompt or reference_image must be provided.",
        )
    job_id = str(uuid.uuid4())
    create_organic_job(
        job_id=job_id,
        prompt=request.prompt,
        provider=request.provider,
        quality_mode=request.quality_mode,
    )

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        try:
            # Stage 1: Analyze prompt
            update_organic_job(job_id, status=OrganicJobStatus.ANALYZING, progress=0.05)
            yield _sse_event(job_id, "analyzing", "Analyzing prompt...", 0.05)

            from backend.core.organic_spec_builder import OrganicSpecBuilder

            builder = OrganicSpecBuilder()
            spec = await builder.build(request)
            update_organic_job(job_id, progress=0.15)
            yield _sse_event(job_id, "analyzing", "Spec built", 0.15)

            # Stage 2: Generate mesh
            update_organic_job(
                job_id, status=OrganicJobStatus.GENERATING, progress=0.2
            )
            yield _sse_event(job_id, "generating", "Generating 3D mesh...", 0.2)

            provider = _create_provider(request.provider, settings)
            upload_result = await _read_uploaded_image(request.reference_image)
            reference_image_bytes = upload_result[0] if upload_result else None
            raw_mesh_path = await provider.generate(
                spec,
                reference_image=reference_image_bytes,
                on_progress=lambda msg, p: None,
            )
            update_organic_job(job_id, progress=0.6)
            yield _sse_event(job_id, "generating", "Mesh generated", 0.6)

            # Stage 3: Post-process
            update_organic_job(
                job_id, status=OrganicJobStatus.POST_PROCESSING, progress=0.65
            )
            yield _sse_event(
                job_id, "post_processing", "Post-processing mesh...", 0.65
            )

            from backend.core.mesh_post_processor import MeshPostProcessor

            processor = MeshPostProcessor()
            processed = await processor.process(raw_mesh_path, spec)
            update_organic_job(job_id, progress=0.9)
            yield _sse_event(
                job_id, "post_processing", "Post-processing complete", 0.9
            )

            # Stage 4: Export & finalize
            output_dir = Path("outputs") / "organic" / job_id
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "model.glb"
            processed.mesh.export(str(output_path))

            result = OrganicJobResult(
                job_id=job_id,
                model_url=f"/outputs/organic/{job_id}/model.glb",
                mesh_stats=processed.stats,
                provider_used=request.provider,
                generation_time_s=0.0,
                post_processing_time_s=0.0,
            )
            update_organic_job(
                job_id,
                status=OrganicJobStatus.COMPLETED,
                progress=1.0,
                result=result,
            )
            result_data = result.model_dump()
            yield _sse_event(
                job_id,
                "completed",
                "Generation complete",
                1.0,
                model_url=result_data.get("model_url"),
                stl_url=result_data.get("stl_url"),
                threemf_url=result_data.get("threemf_url"),
                mesh_stats=result_data.get("mesh_stats"),
            )

        except Exception as e:
            update_organic_job(
                job_id,
                status=OrganicJobStatus.FAILED,
                error=str(e),
            )
            yield _sse_event(job_id, "failed", str(e), 0.0)

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# Image upload endpoint
# ---------------------------------------------------------------------------


@router.post("/generate/organic/upload")
async def generate_organic_upload(
    file: UploadFile = File(...),
    settings: Settings = Depends(_require_organic_enabled),
) -> dict[str, Any]:
    """Upload a reference image for organic generation."""
    # Validate MIME type
    if file.content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(sorted(_ALLOWED_MIME_TYPES))}",
        )

    # Validate file size
    max_bytes = settings.organic_upload_max_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=422,
            detail=f"File too large: {len(content)} bytes. Maximum: {max_bytes} bytes ({settings.organic_upload_max_mb}MB)",
        )

    # Save to temp location
    upload_dir = Path("outputs") / "organic" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    ext = Path(file.filename or "image.png").suffix or _ext_from_mime(file.content_type)
    save_path = upload_dir / f"{file_id}{ext}"
    save_path.write_bytes(content)

    return {"file_id": file_id, "filename": file.filename or "", "size": len(content)}


# ---------------------------------------------------------------------------
# Provider health check (MUST be before /{job_id} to avoid route conflict)
# ---------------------------------------------------------------------------


@router.get("/generate/organic/providers")
async def get_provider_health(
    settings: Settings = Depends(_require_organic_enabled),
) -> dict[str, Any]:
    """Check health of available mesh generation providers."""
    from backend.infra.mesh_providers import HunyuanProvider, TripoProvider

    output_dir = Path("outputs") / "organic"
    tripo = TripoProvider(api_key=settings.tripo3d_api_key, output_dir=output_dir)
    hunyuan = HunyuanProvider(api_key=settings.hunyuan3d_api_key, output_dir=output_dir)

    tripo_ok, hunyuan_ok = await asyncio.gather(
        tripo.check_health(),
        hunyuan.check_health(),
    )

    return {
        "providers": {
            "tripo3d": {
                "available": tripo_ok,
                "configured": bool(settings.tripo3d_api_key),
            },
            "hunyuan3d": {
                "available": hunyuan_ok,
                "configured": bool(settings.hunyuan3d_api_key),
            },
        },
        "default_provider": settings.organic_default_provider,
    }


# ---------------------------------------------------------------------------
# Job status query
# ---------------------------------------------------------------------------


@router.get("/generate/organic/{job_id}")
async def get_organic_job_status(
    job_id: str,
    settings: Settings = Depends(_require_organic_enabled),
) -> dict[str, Any]:
    """Get the status of an organic generation job."""
    job = get_organic_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    response: dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value,
        "progress": job.progress,
        "message": job.message,
        "created_at": job.created_at,
    }
    if job.result:
        response["result"] = job.result.model_dump()
    if job.error:
        response["error"] = job.error
    return response


# ---------------------------------------------------------------------------
# Image upload helper
# ---------------------------------------------------------------------------


async def _read_uploaded_image(file_id: str | None) -> tuple[bytes, str] | None:
    """Read previously uploaded image bytes by file_id.

    Returns (bytes, extension) or None if file_id is empty.
    Raises HTTPException if file_id is invalid or file not found.
    """
    if not file_id:
        return None
    # Validate file_id is a UUID to prevent path traversal
    try:
        uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid file_id: {file_id}") from None
    upload_dir = Path("outputs") / "organic" / "uploads"
    matches = list(upload_dir.glob(f"{file_id}.*"))
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"Uploaded image {file_id} not found. Please re-upload.",
        )
    ext = matches[0].suffix.lstrip(".")  # e.g. "png", "jpg", "webp"
    return matches[0].read_bytes(), ext


# ---------------------------------------------------------------------------
# Provider factory (module-level for mockability)
# ---------------------------------------------------------------------------


def _create_provider(
    provider_name: str,
    settings: Settings,
) -> Any:
    """Create a MeshProvider instance based on the provider name."""
    from backend.infra.mesh_providers import (
        AutoProvider,
        HunyuanProvider,
        TripoProvider,
    )

    output_dir = Path("outputs") / "organic"
    output_dir.mkdir(parents=True, exist_ok=True)

    tripo = TripoProvider(api_key=settings.tripo3d_api_key, output_dir=output_dir)
    hunyuan = HunyuanProvider(
        api_key=settings.hunyuan3d_api_key, output_dir=output_dir
    )

    if provider_name == "tripo3d":
        return tripo
    elif provider_name == "hunyuan3d":
        return hunyuan
    else:  # "auto"
        return AutoProvider(tripo=tripo, hunyuan=hunyuan)
