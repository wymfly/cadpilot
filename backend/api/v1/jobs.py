"""统一 Job 生命周期 API — /api/v1/jobs。

支持三种 input_type：
- text: 参数化模板生成
- drawing: 2D 工程图纸分析
- organic: 文本→3D 有机网格
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.api.v1.errors import (
    APIError,
    ErrorCode,
    InvalidJobStateError,
    JobNotFoundError,
)
from backend.infra.outputs import ensure_job_dir, get_model_url, get_step_path
from backend.models.job import (
    Job,
    JobStatus,
    create_job,
    get_job,
    update_job,
)

# 复用 generate.py 中已验证的辅助函数（pipeline 运行器 + SSE 格式化）
from backend.api.generate import (  # noqa: E402
    _convert_step_to_glb,
    _match_template,
    _parse_intent,
    _run_analyze_drawing,
    _run_generate_from_spec,
    _run_printability_check,
    _run_template_generation,
    _sse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Request / Response 模型
# ---------------------------------------------------------------------------


class CreateJobRequest(BaseModel):
    """统一 Job 创建请求。"""

    input_type: str = "text"  # text | drawing | organic
    text: str = ""
    prompt: str = ""  # organic 模式
    provider: str = "auto"  # organic 模式
    quality_mode: str = "standard"  # organic 模式
    pipeline_config: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    """Job 创建响应。"""

    job_id: str
    status: str


class JobDetailResponse(BaseModel):
    """Job 详情响应。"""

    job_id: str
    status: str
    input_type: str
    input_text: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    printability: dict[str, Any] | None = None


class JobListResponse(BaseModel):
    """Job 列表响应。"""

    items: list[JobDetailResponse]
    total: int
    page: int
    page_size: int


class ConfirmRequest(BaseModel):
    """HITL 参数确认请求（统一文本和图纸模式）。"""

    confirmed_params: dict[str, float] = Field(default_factory=dict)
    confirmed_spec: dict[str, Any] | None = None
    base_body_method: str = "extrude"
    disclaimer_accepted: bool = True


class RegenerateResponse(BaseModel):
    """重新生成响应。"""

    job_id: str
    cloned_from: str
    status: str


# ---------------------------------------------------------------------------
# Job 详情转换
# ---------------------------------------------------------------------------


def _job_to_detail(job: Job) -> JobDetailResponse:
    """将 Job Pydantic 模型转换为 API 响应。"""
    return JobDetailResponse(
        job_id=job.job_id,
        status=job.status.value,
        input_type=job.input_type,
        input_text=job.input_text,
        result=job.result,
        printability=job.printability,
        error=job.error,
        created_at=job.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — 统一创建（返回 SSE 流）
# ---------------------------------------------------------------------------


@router.post("")
async def create_job_endpoint(body: CreateJobRequest) -> EventSourceResponse:
    """创建新 Job，按 input_type 分发管道，返回 SSE 事件流。

    text 模式流程：job_created → intent_parsed → awaiting_confirmation
    """
    from loguru import logger

    job_id = str(uuid.uuid4())
    input_text = body.text or body.prompt
    job = await create_job(job_id, input_type=body.input_type, input_text=input_text)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("job_created", {"job_id": job.job_id, "status": job.status.value})

        # text 模式：解析意图 → 参数确认
        matched_template: Any = None
        params: list[Any] = []
        intent_data: dict[str, Any] | None = None

        try:
            intent = await _parse_intent(input_text)
            intent_data = intent.model_dump(mode="json")
            if intent.confidence > 0.7 and intent.part_type:
                try:
                    from backend.core.template_engine import TemplateEngine

                    _tpl_dir = Path(__file__).parent.parent.parent / "knowledge" / "templates"
                    engine = TemplateEngine.from_directory(_tpl_dir)
                    matches = engine.find_matches(intent.part_type.value)
                    if matches:
                        matched_template = matches[0]
                        params = matches[0].params
                except Exception as exc:
                    logger.warning("Template matching failed for job %s: %s", job_id, exc)
        except Exception as exc:
            logger.warning("IntentParser failed for job %s, falling back to keyword matching: %s", job_id, exc)

        if matched_template is None:
            matched_template, params = _match_template(input_text)

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

        await update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)
        yield _sse("awaiting_confirmation", {
            "job_id": job_id,
            "status": JobStatus.AWAITING_CONFIRMATION.value,
            "message": "请确认参数后继续",
        })

    return EventSourceResponse(event_stream())


@router.post("/upload")
async def create_drawing_job(
    image: UploadFile = File(...),
    pipeline_config: str = Form("{}"),
) -> EventSourceResponse:
    """创建图纸模式 Job（multipart 上传），返回 SSE 事件流。

    流程：job_created → analyzing → drawing_spec_ready | failed
    """
    # 文件大小限制：20MB
    max_size = 20 * 1024 * 1024
    content = await image.read()
    if len(content) > max_size:
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"文件过大：{len(content)} 字节，上限 {max_size} 字节",
        )

    job_id = str(uuid.uuid4())
    job = await create_job(job_id, input_type="drawing")

    # 保存上传图片
    job_dir = ensure_job_dir(job_id)
    ext = Path(image.filename or "input.png").suffix or ".png"
    image_path = str(job_dir / f"input{ext}")
    await asyncio.to_thread(Path(image_path).write_bytes, content)
    await update_job(job_id, image_path=image_path)

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("job_created", {"job_id": job.job_id, "status": job.status.value})

        yield _sse("analyzing", {
            "job_id": job_id,
            "status": "analyzing",
            "message": "正在分析图纸…",
        })

        try:
            spec, reasoning = await asyncio.to_thread(_run_analyze_drawing, image_path)
        except Exception as exc:
            await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"图纸分析失败: {exc}",
            })
            return

        if spec is None:
            await update_job(job_id, status=JobStatus.FAILED, error="图纸分析返回空结果")
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": "图纸分析返回空结果",
            })
            return

        # 尝试序列化 spec（测试中可能返回 MagicMock 等不可序列化对象）
        try:
            import json as _json
            spec_data = spec.model_dump(mode="json") if hasattr(spec, "model_dump") else spec
            _json.dumps(spec_data)  # 验证可序列化
        except Exception as exc:
            await update_job(job_id, status=JobStatus.FAILED, error=f"图纸分析结果无效: {exc}")
            yield _sse("failed", {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "message": f"图纸分析结果无效: {exc}",
            })
            return

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

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# GET /api/v1/jobs — 分页列表
# ---------------------------------------------------------------------------


@router.get("", response_model=JobListResponse)
async def list_jobs_endpoint(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    input_type: str | None = None,
) -> JobListResponse:
    """返回 Job 分页列表。"""
    from backend.db.database import async_session
    from backend.db.repository import list_jobs as repo_list

    async with async_session() as session:
        orm_jobs, total = await repo_list(
            session,
            page=page,
            page_size=page_size,
            status=status,
            input_type=input_type,
        )

    # 转换 ORM → Pydantic
    from backend.models.job import _orm_to_job

    items = [_job_to_detail(_orm_to_job(j)) for j in orm_jobs]
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id} — 详情
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job_endpoint(job_id: str) -> JobDetailResponse:
    """返回 Job 详情。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return _job_to_detail(job)


# ---------------------------------------------------------------------------
# DELETE /api/v1/jobs/{job_id} — 软删除
# ---------------------------------------------------------------------------


@router.delete("/{job_id}")
async def delete_job_endpoint(job_id: str) -> dict[str, str]:
    """软删除 Job（设置 deleted_at 时间戳）。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    from backend.db.database import async_session
    from backend.db.repository import soft_delete_job

    async with async_session() as session:
        await soft_delete_job(session, job_id)
        await session.commit()

    return {"job_id": job_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{job_id}/confirm — HITL 确认
# ---------------------------------------------------------------------------


@router.post("/{job_id}/confirm")
async def confirm_job(job_id: str, body: ConfirmRequest) -> EventSourceResponse:
    """确认 AI 分析结果，恢复管道执行，返回 SSE 事件流。

    文本模式（awaiting_confirmation）：generating → refining → completed | failed
    图纸模式（awaiting_drawing_confirmation）：generating → refining → completed | failed
    """
    from loguru import logger
    from backend.pipeline.sse_bridge import PipelineBridge

    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    valid_states = {
        JobStatus.AWAITING_CONFIRMATION,
        JobStatus.AWAITING_DRAWING_CONFIRMATION,
    }
    if job.status not in valid_states:
        raise InvalidJobStateError(
            job_id,
            current=job.status.value,
            expected="awaiting_confirmation",
        )

    # 收集用户修正（仅图纸模式，有原始 spec 时）
    if body.confirmed_spec and job.drawing_spec:
        try:
            from backend.core.correction_tracker import (
                compute_corrections,
                persist_corrections,
            )

            corrections = compute_corrections(job.drawing_spec, body.confirmed_spec, job_id)
            if corrections:
                await asyncio.to_thread(persist_corrections, job_id, corrections)
        except Exception:
            pass  # 修正收集失败不阻塞主流程

    # 图纸模式：验证免责声明
    is_drawing_mode = job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
    if is_drawing_mode and not body.disclaimer_accepted:
        raise APIError(
            status_code=400,
            code=ErrorCode.VALIDATION_FAILED,
            message="免责声明必须接受后方可继续生成",
        )

    # 保存确认数据，切换为生成中
    update_kwargs: dict[str, Any] = {"status": JobStatus.GENERATING}
    if body.confirmed_spec:
        update_kwargs["drawing_spec_confirmed"] = body.confirmed_spec
    await update_job(job_id, **update_kwargs)

    job_dir = ensure_job_dir(job_id)
    step_path = str(get_step_path(job_id))
    glb_path = str(job_dir / "model.glb")

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        yield _sse("generating", {
            "job_id": job_id,
            "status": JobStatus.GENERATING.value,
            "message": "参数已确认，正在生成 3D 模型…",
        })

        if is_drawing_mode:
            # ---- 图纸模式：使用 PipelineBridge 流式输出进度 ----
            bridge = PipelineBridge(job_id)

            try:
                from backend.knowledge.part_types import DrawingSpec

                confirmed_spec = DrawingSpec(**(body.confirmed_spec or {}))
            except Exception as exc:
                await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
                yield _sse("failed", {
                    "job_id": job_id,
                    "status": JobStatus.FAILED.value,
                    "message": f"参数解析失败: {exc}",
                })
                return

            image_path = job.image_path
            pipeline_task = asyncio.ensure_future(asyncio.to_thread(
                _run_generate_from_spec,
                image_filepath=image_path,
                drawing_spec=confirmed_spec,
                output_filepath=step_path,
                on_progress=bridge.on_progress,
            ))

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

            # 耗尽剩余事件（防止竞态）
            while not bridge.queue.empty():
                event = bridge.queue.get_nowait()
                event_type = event.get("event", "progress")
                data = event.get("data", {})
                payload = {"job_id": job_id, **data, "status": event_type}
                if event_type == "refining":
                    await update_job(job_id, status=JobStatus.REFINING)
                yield _sse(event_type, payload)

            pipeline_failed = False
            try:
                pipeline_task.result()
            except Exception as exc:
                pipeline_failed = True
                logger.error("Drawing pipeline failed for job {}: {}", job_id, exc)
                await update_job(job_id, status=JobStatus.FAILED, error=str(exc))
                yield _sse("failed", {
                    "job_id": job_id,
                    "status": JobStatus.FAILED.value,
                    "message": f"管道执行失败: {exc}",
                })

            if not pipeline_failed and Path(step_path).exists():
                await _finalize_job(job_id, step_path, glb_path, body.confirmed_spec or {})
                async for evt in _finalize_sse(job_id, step_path, glb_path, body.confirmed_spec or {}):
                    yield evt
            elif not pipeline_failed:
                await update_job(job_id, status=JobStatus.FAILED, error="管道执行完成但未生成 STEP 文件")
                yield _sse("failed", {
                    "job_id": job_id,
                    "status": JobStatus.FAILED.value,
                    "message": "管道执行完成但未生成 STEP 文件",
                })

        else:
            # ---- 文本模式：使用参数化模板 ----
            try:
                success = await asyncio.to_thread(
                    _run_template_generation, job, body.confirmed_params, step_path,
                )

                if success and Path(step_path).exists():
                    async for evt in _finalize_sse(job_id, step_path, glb_path, body.confirmed_params):
                        yield evt
                else:
                    # 无模板匹配或执行失败 — 优雅降级完成
                    await update_job(job_id, status=JobStatus.REFINING)
                    yield _sse("refining", {
                        "job_id": job_id,
                        "status": JobStatus.REFINING.value,
                        "message": "正在优化模型…",
                    })
                    await update_job(
                        job_id,
                        status=JobStatus.COMPLETED,
                        result={"message": "生成完成", "confirmed_params": body.confirmed_params},
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


async def _finalize_job(
    job_id: str,
    step_path: str,
    glb_path: str,
    confirmed_data: dict[str, Any],
) -> None:
    """更新 DB 为 COMPLETED（内部辅助，不产生 SSE）。"""
    from loguru import logger

    model_url: str | None = None
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_convert_step_to_glb, step_path, glb_path),
            timeout=30,
        )
        model_url = get_model_url(job_id, fmt="glb")
    except Exception as exc:
        logger.warning("STEP→GLB conversion failed for job {}: {}", job_id, exc)

    printability_data = await asyncio.to_thread(_run_printability_check, step_path)

    try:
        await update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "model_url": model_url,
                "step_path": step_path,
                "confirmed_data": confirmed_data,
            },
            printability_result=printability_data,
        )
    except Exception as exc:
        from loguru import logger as _logger
        _logger.error("Failed to update job {} to COMPLETED: {}", job_id, exc)


async def _finalize_sse(
    job_id: str,
    step_path: str,
    glb_path: str,
    confirmed_data: dict[str, Any],
) -> AsyncGenerator[dict[str, str], None]:
    """生成 refining + completed SSE 事件序列（内部辅助）。"""
    from loguru import logger

    await update_job(job_id, status=JobStatus.REFINING)
    yield _sse("refining", {
        "job_id": job_id,
        "status": JobStatus.REFINING.value,
        "message": "正在转换预览格式…",
    })

    model_url: str | None = None
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_convert_step_to_glb, step_path, glb_path),
            timeout=30,
        )
        model_url = get_model_url(job_id, fmt="glb")
    except Exception as exc:
        logger.warning("STEP→GLB conversion failed for job {}: {}", job_id, exc)

    printability_data = await asyncio.to_thread(_run_printability_check, step_path)

    try:
        await update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "model_url": model_url,
                "step_path": step_path,
                "confirmed_data": confirmed_data,
            },
            printability_result=printability_data,
        )
    except Exception as exc:
        logger.error("Failed to update job {} to COMPLETED: {}", job_id, exc)

    yield _sse("completed", {
        "job_id": job_id,
        "status": JobStatus.COMPLETED.value,
        "message": "生成完成",
        "model_url": model_url,
        "step_path": step_path,
        "printability": printability_data,
    })


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{job_id}/regenerate — 重新生成
# ---------------------------------------------------------------------------


@router.post("/{job_id}/regenerate", response_model=RegenerateResponse)
async def regenerate_job(job_id: str) -> RegenerateResponse:
    """基于已有 Job 参数创建新 Job。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    new_job_id = str(uuid.uuid4())
    await create_job(new_job_id, input_type=job.input_type, input_text=job.input_text)

    return RegenerateResponse(job_id=new_job_id, cloned_from=job_id, status="created")


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}/corrections — 用户修正记录
# ---------------------------------------------------------------------------


class CorrectionItem(BaseModel):
    """单条用户修正记录。"""

    field_path: str
    original_value: str
    corrected_value: str
    timestamp: str


@router.get("/{job_id}/corrections")
async def get_job_corrections(job_id: str) -> list[CorrectionItem]:
    """返回 Job 的所有用户修正记录。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    from backend.db.database import async_session
    from backend.db.repository import list_corrections_by_job

    async with async_session() as session:
        corrections = await list_corrections_by_job(session, job_id)

    return [
        CorrectionItem(
            field_path=c.field_path,
            original_value=c.original_value,
            corrected_value=c.corrected_value,
            timestamp=c.timestamp.isoformat() if c.timestamp else "",
        )
        for c in corrections
    ]
