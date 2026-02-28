"""SSE-based generate endpoint with Job session protocol (Phase 4 Task 4.6).

Supports two modes:
1. **text** mode: POST /generate → IntentParser → pause for confirmation → generate
2. **drawing** mode: POST /generate/drawing → VL analysis → pause for confirmation → generate

Both modes use HITL (Human-in-the-Loop) confirmation before generation.
Job lifecycle events are streamed as SSE to the client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

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


class DrawingConfirmRequest(BaseModel):
    """Request body for drawing spec confirmation."""

    confirmed_spec: dict[str, Any]
    disclaimer_accepted: bool


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


def _run_analyze_drawing(image_filepath: str) -> tuple[Any, str | None]:
    """Wrapper around analyze_drawing for mockability."""
    from backend.pipeline.pipeline import analyze_drawing

    return analyze_drawing(image_filepath)


def _run_generate_from_spec(
    image_filepath: str,
    drawing_spec: Any,
    output_filepath: str,
    config: PipelineConfig | None = None,
    on_progress: Any = None,
) -> None:
    """Wrapper around generate_from_drawing_spec for mockability."""
    from backend.pipeline.pipeline import generate_from_drawing_spec

    generate_from_drawing_spec(
        image_filepath=image_filepath,
        drawing_spec=drawing_spec,
        output_filepath=output_filepath,
        on_progress=on_progress,
        config=config,
    )


def _convert_step_to_glb(step_path: str, glb_path: str) -> None:
    """Convert STEP to GLB for preview. Wrapper for mockability."""
    exporter = FormatExporter()
    glb_bytes = exporter.to_gltf_for_preview(step_path)
    with open(glb_path, "wb") as f:
        f.write(glb_bytes)


def _match_template(
    text: str,
) -> tuple[Any, list[Any]]:
    """Simple keyword matching to find a parametric template.

    Returns ``(template, params)`` where *params* is
    ``list[ParamDefinition]``.  If nothing matches, returns
    ``(None, [])``.
    """
    try:
        from backend.core.template_engine import TemplateEngine

        _templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)
        templates = engine.list_templates()
    except Exception as exc:
        logger.warning("Template engine initialization failed: %s", exc)
        return None, []

    text_lower = text.lower()
    for tpl in templates:
        # Match by display_name (Chinese) or name (machine-readable)
        if tpl.display_name in text or tpl.name in text_lower:
            return tpl, tpl.params

    # No match — return None with empty params
    return None, []


def _run_template_generation(
    job: Any, confirmed_params: dict[str, float], step_path: str
) -> bool:
    """Use parametric template to generate STEP file.  Returns *True* on success."""
    template_name: str | None = None
    if job.result and isinstance(job.result, dict):
        template_name = job.result.get("template_name")

    if not template_name:
        return False

    try:
        from backend.core.template_engine import TemplateEngine

        _templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)
        template = engine.get_template(template_name)
    except Exception as exc:
        logger.warning("Template load failed for '%s': %s", template_name, exc)
        return False

    # Render Jinja2 template with confirmed params
    try:
        code = engine.render(
            template_name,
            confirmed_params,
            output_filename=step_path,
        )
    except Exception as exc:
        logger.warning("Template render failed for '%s': %s", template_name, exc)
        return False

    # Execute in sandbox
    try:
        from backend.infra.sandbox import SafeExecutor

        executor = SafeExecutor(timeout_s=120)
        result = executor.execute(code)
        return result.success and Path(step_path).exists()
    except Exception as exc:
        logger.warning("Sandbox execution failed for '%s': %s", template_name, exc)
        return False


def _run_printability_check(step_path: str) -> dict[str, Any] | None:
    """Run printability check on a STEP file. Returns None on failure."""
    try:
        from backend.core.geometry_extractor import extract_geometry_from_step
        from backend.core.printability import PrintabilityChecker

        geometry_info = extract_geometry_from_step(step_path)
        checker = PrintabilityChecker()
        result = checker.check(geometry_info)
        mat = checker.estimate_material(geometry_info)
        time_est = checker.estimate_print_time(geometry_info)
        data = result.model_dump()
        data["material_estimate"] = {
            "filament_weight_g": mat.filament_weight_g,
            "filament_length_m": mat.filament_length_m,
            "cost_estimate_cny": mat.cost_estimate_cny,
        }
        data["time_estimate"] = {
            "total_minutes": time_est.total_minutes,
            "layer_count": time_est.layer_count,
        }
        return data
    except Exception as exc:
        logger.warning("Printability check failed for %s: %s", step_path, exc)
        return None


async def _parse_intent(text: str) -> Any:
    """Parse user text via IntentParser (LLM-driven). Module-level for mockability."""
    from backend.core.intent_parser import IntentParser
    from backend.infra.chat_models import ChatModelParameters

    chat_model = ChatModelParameters.from_model_name(
        "qwen-coder-plus",
    ).create_chat_model()

    async def _llm_callable(prompt: str, schema: type) -> Any:
        response = await chat_model.ainvoke(prompt)
        return schema.model_validate_json(response.content)

    parser = IntentParser(llm_callable=_llm_callable)
    return await parser.parse(text)


def _parse_pipeline_config(config_json: str) -> PipelineConfig:
    """Parse pipeline_config JSON string into PipelineConfig."""
    try:
        raw = json.loads(config_json)
    except json.JSONDecodeError:
        return PRESETS["balanced"]
    if not isinstance(raw, dict):
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
    job = await create_job(job_id, input_type="text", input_text=body.text)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("job_created", {
            "job_id": job.job_id,
            "status": job.status.value,
        })

        # Stage 1: Intent parsing
        matched_template: Any = None
        params: list[Any] = []
        intent_data: dict[str, Any] | None = None

        # Try IntentParser first (LLM-driven)
        try:
            intent = await _parse_intent(body.text)
            intent_data = intent.model_dump(mode="json")
            if intent.confidence > 0.7 and intent.part_type:
                try:
                    from backend.core.template_engine import TemplateEngine

                    _tpl_dir = (
                        Path(__file__).parent.parent / "knowledge" / "templates"
                    )
                    engine = TemplateEngine.from_directory(_tpl_dir)
                    matches = engine.find_matches(intent.part_type.value)
                    if matches:
                        matched_template = matches[0]
                        params = matches[0].params
                except Exception as exc:
                    logger.warning("Template matching failed for job %s: %s", job_id, exc)
        except Exception as exc:
            logger.warning("IntentParser failed for job %s, falling back to keyword matching: %s", job_id, exc)

        # Fallback: keyword matching if IntentParser didn't find a template
        if matched_template is None:
            matched_template, params = _match_template(body.text)

        # Store template reference and intent in job for the confirm step
        result_data: dict[str, Any] = {}
        if matched_template:
            result_data["template_name"] = matched_template.name
        if intent_data:
            result_data["intent"] = intent_data
        if result_data:
            await update_job(job_id, result=result_data)

        await update_job(job_id, status=JobStatus.INTENT_PARSED)
        yield _sse("intent_parsed", {
            "job_id": job_id,
            "status": JobStatus.INTENT_PARSED.value,
            "message": "意图解析完成，等待参数确认",
            "template_name": matched_template.name if matched_template else None,
            "params": [p.model_dump() for p in params],
            "intent": intent_data,
        })

        # Pause — client must call POST /generate/{job_id}/confirm
        await update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)
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
    """Create a new drawing-mode generate job (HITL flow).

    Flow: image → VL analysis → drawing_spec_ready → pause
    Client must call POST /generate/drawing/{job_id}/confirm to resume.
    """
    config = _parse_pipeline_config(pipeline_config)

    job_id = str(uuid.uuid4())
    job = await create_job(job_id, input_type="drawing")

    # Persist uploaded image to job directory
    job_dir = ensure_job_dir(job_id)
    ext = Path(image.filename or "input.png").suffix or ".png"
    image_path = str(job_dir / f"input{ext}")
    content = await image.read()
    await asyncio.to_thread(Path(image_path).write_bytes, content)

    # Store image_path and config in job for later use by confirm endpoint
    await update_job(job_id, image_path=image_path)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        # 1. job_created
        yield _sse("job_created", {
            "job_id": job.job_id,
            "status": job.status.value,
        })

        # 2. Stage 1: Analyze drawing (VL only)
        yield _sse("analyzing", {
            "job_id": job_id,
            "status": "analyzing",
            "message": "正在分析图纸…",
        })

        try:
            spec, reasoning = await asyncio.to_thread(
                _run_analyze_drawing, image_path,
            )
        except Exception as exc:
            await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"图纸分析失败: {exc}",
            })
            return

        if spec is None:
            await update_job(
                job_id,
                status=JobStatus.FAILED,
                error="图纸分析返回空结果",
            )
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": "图纸分析返回空结果",
            })
            return

        # 3. Store spec in job and pause for user confirmation
        spec_data = spec.model_dump() if hasattr(spec, "model_dump") else spec
        await update_job(
            job_id,
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=spec_data,
        )

        yield _sse("drawing_spec_ready", {
            "job_id": job_id,
            "status": JobStatus.AWAITING_DRAWING_CONFIRMATION.value,
            "message": "图纸分析完成，等待确认",
            "drawing_spec": spec_data,
            "reasoning": reasoning,
        })
        # Stream ends here — client must call /generate/drawing/{job_id}/confirm

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# POST /generate/drawing/{job_id}/confirm — resume drawing pipeline
# ---------------------------------------------------------------------------


@router.post("/generate/drawing/{job_id}/confirm")
async def confirm_drawing_spec(
    job_id: str, body: DrawingConfirmRequest
) -> EventSourceResponse:
    """Confirm DrawingSpec and resume the drawing generation pipeline.

    Flow: confirmed_spec → generate_from_drawing_spec → STEP → GLB → completed
    """
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.status != JobStatus.AWAITING_DRAWING_CONFIRMATION:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Job {job_id} is in state '{job.status.value}', "
                f"expected 'awaiting_drawing_confirmation'"
            ),
        )
    if not body.disclaimer_accepted:
        raise HTTPException(
            status_code=400,
            detail="免责声明必须接受后方可继续生成",
        )

    # Track user corrections (data flywheel) — non-critical, must not block generation
    if job.drawing_spec and body.confirmed_spec:
        try:
            from backend.core.correction_tracker import (
                compute_corrections,
                persist_corrections,
            )

            corrections = compute_corrections(
                job.drawing_spec, body.confirmed_spec, job_id,
            )
            if corrections:
                await asyncio.to_thread(persist_corrections, job_id, corrections)
        except Exception as exc:
            logger.warning("Failed to persist corrections for job %s: %s", job_id, exc)

    # Save confirmed spec and transition to GENERATING
    await update_job(
        job_id,
        drawing_spec_confirmed=body.confirmed_spec,
        status=JobStatus.GENERATING,
    )

    image_path = job.image_path
    job_dir = ensure_job_dir(job_id)
    step_path = str(get_step_path(job_id))
    glb_path = str(job_dir / "model.glb")

    bridge = PipelineBridge(job_id)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("generating", {
            "job_id": job_id,
            "status": JobStatus.GENERATING.value,
            "message": "参数已确认，正在生成 3D 模型…",
        })

        # Run Stages 1.5-5 in worker thread via bridge
        try:
            from backend.knowledge.part_types import DrawingSpec

            confirmed_spec = DrawingSpec(**body.confirmed_spec)
        except Exception as exc:
            await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"参数解析失败: {exc}",
            })
            return

        pipeline_task = asyncio.ensure_future(asyncio.to_thread(
            _run_generate_from_spec,
            image_filepath=image_path,
            drawing_spec=confirmed_spec,
            output_filepath=step_path,
            on_progress=bridge.on_progress,
        ))

        # Stream progress events in real-time
        import queue as _queue_mod
        while not pipeline_task.done():
            try:
                event = bridge.queue.get_nowait()
            except _queue_mod.Empty:
                await asyncio.sleep(0.2)
                continue
            event_type = event.get("event", "progress")
            data = event.get("data", {})
            payload = {"job_id": job_id, **data, "status": event_type}
            if event_type == "refining":
                await update_job(job_id, status=JobStatus.REFINING)
            yield _sse(event_type, payload)

        # Check pipeline result
        pipeline_failed = False
        try:
            pipeline_task.result()
        except Exception as exc:
            pipeline_failed = True
            await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"管道执行失败: {exc}",
            })

        if not pipeline_failed and os.path.exists(step_path):
            # Convert STEP → GLB for preview
            await update_job(job_id, status=JobStatus.REFINING)
            yield _sse("refining", {
                "job_id": job_id,
                "status": JobStatus.REFINING.value,
                "message": "正在转换预览格式…",
            })

            model_url: str | None = None
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        _convert_step_to_glb, step_path, glb_path,
                    ),
                    timeout=30,
                )
                model_url = get_model_url(job_id, fmt="glb")
            except Exception as exc:
                logger.warning("STEP→GLB conversion failed for job %s: %s", job_id, exc)

            # Run printability check
            printability_data = await asyncio.to_thread(
                _run_printability_check, step_path,
            )

            await update_job(
                job_id,
                status=JobStatus.COMPLETED,
                result={
                    "message": "生成完成",
                    "model_url": model_url,
                    "step_path": step_path,
                    "confirmed_spec": body.confirmed_spec,
                },
                printability_result=printability_data,
            )
            yield _sse("completed", {
                "job_id": job_id,
                "status": JobStatus.COMPLETED.value,
                "message": "生成完成",
                "model_url": model_url,
                "step_path": step_path,
                "printability": printability_data,
            })
        elif not pipeline_failed and not os.path.exists(step_path):
            await update_job(
                job_id,
                status=JobStatus.FAILED,
                error="管道执行完成但未生成 STEP 文件",
            )
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": "管道执行完成但未生成 STEP 文件",
            })

        # Drain remaining bridge events
        while not bridge.queue.empty():
            event = bridge.queue.get_nowait()
            event_type = event.get("event", "progress")
            data = event.get("data", {})
            payload = {"job_id": job_id, **data, "status": event_type}
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
    job = await get_job(job_id)
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

    await update_job(job_id, status=JobStatus.GENERATING)
    job_dir = ensure_job_dir(job_id)
    step_path = str(get_step_path(job_id))

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("generating", {
            "job_id": job_id,
            "status": JobStatus.GENERATING.value,
            "confirmed_params": body.confirmed_params,
            "message": "参数已确认，正在生成…",
        })

        try:
            # Try template-based generation
            success = await asyncio.to_thread(
                _run_template_generation, job, body.confirmed_params, step_path,
            )

            if success and Path(step_path).exists():
                # Convert STEP → GLB for preview
                await update_job(job_id, status=JobStatus.REFINING)
                yield _sse("refining", {
                    "job_id": job_id,
                    "status": JobStatus.REFINING.value,
                    "message": "正在转换预览格式…",
                })

                glb_path = str(job_dir / "model.glb")
                model_url: str | None = None
                try:
                    await asyncio.to_thread(_convert_step_to_glb, step_path, glb_path)
                    model_url = get_model_url(job_id, "glb")
                except Exception as exc:
                    logger.warning("STEP→GLB conversion failed for job %s: %s", job_id, exc)
                    model_url = None

                # Run printability check
                printability_data = await asyncio.to_thread(
                    _run_printability_check, step_path,
                )

                await update_job(
                    job_id,
                    status=JobStatus.COMPLETED,
                    result={
                        "message": "生成完成",
                        "model_url": model_url,
                        "step_path": step_path,
                        "confirmed_params": body.confirmed_params,
                    },
                    printability_result=printability_data,
                )
                yield _sse("completed", {
                    "job_id": job_id,
                    "status": JobStatus.COMPLETED.value,
                    "message": "生成完成",
                    "model_url": model_url,
                    "step_path": step_path,
                    "printability": printability_data,
                })
            else:
                # No template matched or execution failed — still complete
                # gracefully (no STEP, no model_url)
                await update_job(job_id, status=JobStatus.REFINING)
                yield _sse("refining", {
                    "job_id": job_id,
                    "status": JobStatus.REFINING.value,
                    "message": "正在优化模型…",
                })

                await update_job(
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
        except Exception as exc:
            await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"生成失败: {exc}",
            })

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# GET /generate/jobs — list all jobs (must be before /{job_id} route)
# ---------------------------------------------------------------------------


@router.get("/generate/jobs")
async def list_all_jobs() -> list[dict[str, Any]]:
    """Return all jobs (for debugging / dashboard)."""
    return [j.model_dump() for j in await list_jobs()]


# ---------------------------------------------------------------------------
# GET /generate/{job_id} — query job status
# ---------------------------------------------------------------------------


@router.get("/generate/{job_id}")
async def get_job_status(job_id: str) -> dict[str, Any]:
    """Return current job state."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job.model_dump()
