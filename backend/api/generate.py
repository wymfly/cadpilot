"""SSE-based generate endpoint with Job session protocol (Phase 4 Task 4.6).

Supports two modes:
1. **text** mode: POST /generate/text → IntentParser → pause for confirmation → generate
2. **drawing** mode: POST /generate/drawing → V2 Pipeline → direct generate

Job lifecycle events are streamed as SSE to the client.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.core.format_exporter import FormatExporter
from backend.infra.outputs import ensure_job_dir, get_model_url, get_step_path
from backend.models.job import (
    JobStatus,
    clear_jobs,
    create_job,
    get_job,
    list_jobs,
    update_job,
)
from backend.models.pipeline_config import PRESETS, PipelineConfig
from backend.pipeline.sse_bridge import PipelineBridge

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class TextGenerateRequest(BaseModel):
    """Request body for text-based generation."""

    text: str
    pipeline_config: dict[str, Any] = {}


class ConfirmRequest(BaseModel):
    """Request body for parameter confirmation."""

    confirmed_params: dict[str, float] = {}
    base_body_method: str = "extrude"


# ---------------------------------------------------------------------------
# SSE event helpers
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict[str, Any]) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


# ---------------------------------------------------------------------------
# Pipeline helper wrappers (module-level for mockability)
# ---------------------------------------------------------------------------


def _run_v2_pipeline(
    image_filepath: str,
    output_filepath: str,
    config: PipelineConfig | None = None,
    on_spec_ready: Any = None,
    on_progress: Any = None,
) -> None:
    """Wrapper around generate_step_v2 for mockability."""
    from backend.pipeline.pipeline import generate_step_v2

    generate_step_v2(
        image_filepath=image_filepath,
        output_filepath=output_filepath,
        config=config,
        on_spec_ready=on_spec_ready,
        on_progress=on_progress,
    )


def _convert_step_to_glb(step_path: str, glb_path: str) -> None:
    """Convert STEP to GLB for preview. Wrapper for mockability."""
    exporter = FormatExporter()
    glb_bytes = exporter.to_gltf_for_preview(step_path)
    with open(glb_path, "wb") as f:
        f.write(glb_bytes)


def _parse_pipeline_config(config_json: str) -> PipelineConfig:
    """Parse pipeline_config JSON string into PipelineConfig."""
    try:
        raw = json.loads(config_json)
    except json.JSONDecodeError:
        return PRESETS["balanced"]
    preset = raw.get("preset", "balanced")
    if preset in PRESETS and len(raw) <= 2:  # only preset key (+ maybe extra)
        return PRESETS[preset]
    return PipelineConfig(**raw)


# ---------------------------------------------------------------------------
# POST /generate — text mode (JSON body)
# ---------------------------------------------------------------------------


@router.post("/generate")
async def generate_text(body: TextGenerateRequest) -> EventSourceResponse:
    """Create a new text-mode generate job.

    Flow: text → IntentParser → pause for confirmation → generate
    """
    job_id = str(uuid.uuid4())
    job = create_job(job_id, input_type="text", input_text=body.text)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("job_created", {
            "job_id": job.job_id,
            "status": job.status.value,
        })

        # Stage 1: Intent parsing
        update_job(job_id, status=JobStatus.INTENT_PARSED)
        yield _sse("intent_parsed", {
            "job_id": job_id,
            "status": JobStatus.INTENT_PARSED.value,
            "message": "意图解析完成，等待参数确认",
        })

        # Pause — client must call POST /generate/{job_id}/confirm
        update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)
        yield _sse("awaiting_confirmation", {
            "job_id": job_id,
            "status": JobStatus.AWAITING_CONFIRMATION.value,
            "message": "请确认参数后继续",
        })

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# POST /generate/drawing — drawing mode (multipart)
# ---------------------------------------------------------------------------


@router.post("/generate/drawing")
async def generate_drawing(
    image: UploadFile = File(...),
    pipeline_config: str = Form("{}"),
) -> EventSourceResponse:
    """Create a new drawing-mode generate job.

    Flow: image → V2 Pipeline → STEP → GLB → completed with model_url
    """
    config = _parse_pipeline_config(pipeline_config)

    job_id = str(uuid.uuid4())
    job = create_job(job_id, input_type="drawing")

    # Persist uploaded image to job directory
    job_dir = ensure_job_dir(job_id)
    ext = Path(image.filename or "input.png").suffix or ".png"
    image_path = str(job_dir / f"input{ext}")
    content = await image.read()
    with open(image_path, "wb") as f:
        f.write(content)

    step_path = str(get_step_path(job_id))
    glb_path = str(job_dir / "model.glb")

    bridge = PipelineBridge(job_id)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        # 1. job_created
        yield _sse("job_created", {
            "job_id": job.job_id,
            "status": job.status.value,
        })

        update_job(job_id, status=JobStatus.GENERATING)
        yield _sse("generating", {
            "job_id": job_id,
            "status": JobStatus.GENERATING.value,
            "message": "正在生成 3D 模型…",
        })

        # 2. Run V2 pipeline in worker thread
        try:
            await asyncio.to_thread(
                _run_v2_pipeline,
                image_filepath=image_path,
                output_filepath=step_path,
                config=config,
                on_spec_ready=bridge.on_spec_ready,
                on_progress=bridge.on_progress,
            )

            # 3. Convert STEP → GLB for preview
            if os.path.exists(step_path):
                await asyncio.to_thread(_convert_step_to_glb, step_path, glb_path)
                model_url = get_model_url(job_id, fmt="glb")
                bridge.complete(model_url=model_url, step_path=step_path)
            else:
                bridge.fail("管道执行完成但未生成 STEP 文件")

        except Exception as exc:
            bridge.fail(f"管道执行失败: {exc}")

        # 4. Drain bridge queue → SSE events
        while not bridge.queue.empty():
            event = bridge.queue.get_nowait()
            event_type = event.get("event", "progress")
            data = event.get("data", {})
            payload = {
                "job_id": job_id,
                "status": event_type,
                **data,
            }

            # Update job status for terminal events
            if event_type == "completed":
                update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    result=data,
                )
            elif event_type == "failed":
                update_job(
                    job_id,
                    status=JobStatus.FAILED,
                    error=data.get("message", "unknown error"),
                )
            elif event_type == "refining":
                update_job(job_id, status=JobStatus.REFINING)

            yield _sse(event_type, payload)

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# POST /generate/{job_id}/confirm — resume after parameter confirmation
# ---------------------------------------------------------------------------


@router.post("/generate/{job_id}/confirm")
async def confirm_params(
    job_id: str, body: ConfirmRequest
) -> EventSourceResponse:
    """Confirm parameters and resume the generate pipeline."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != JobStatus.AWAITING_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} is in state '{job.status.value}', "
                f"expected 'awaiting_confirmation'"
            ),
        )

    update_job(job_id, status=JobStatus.GENERATING)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("generating", {
            "job_id": job_id,
            "status": JobStatus.GENERATING.value,
            "confirmed_params": body.confirmed_params,
            "message": "参数已确认，正在生成…",
        })

        # Stage: refining
        update_job(job_id, status=JobStatus.REFINING)
        yield _sse("refining", {
            "job_id": job_id,
            "status": JobStatus.REFINING.value,
            "message": "正在优化模型…",
        })

        # Stage: completed
        update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "confirmed_params": body.confirmed_params,
            },
        )
        yield _sse("completed", {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "message": "生成完成",
        })

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# GET /generate/jobs — list all jobs (must be before /{job_id} route)
# ---------------------------------------------------------------------------


@router.get("/generate/jobs")
async def list_all_jobs() -> list[dict[str, Any]]:
    """Return all jobs (for debugging / dashboard)."""
    return [j.model_dump() for j in list_jobs()]


# ---------------------------------------------------------------------------
# GET /generate/{job_id} — query job status
# ---------------------------------------------------------------------------


@router.get("/generate/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Return current job state."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job.model_dump()
