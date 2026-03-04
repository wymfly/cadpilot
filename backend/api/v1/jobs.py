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

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.api.v1.errors import (
    APIError,
    ErrorCode,
    InvalidJobStateError,
    JobNotFoundError,
)
from backend.infra.outputs import ensure_job_dir
from backend.models.job import (
    Job,
    JobStatus,
    create_job,
    get_job,
)

# SSE 格式化辅助（pipeline helper 由 LangGraph 节点替代）
from backend.api.v1.events import _sse, emit_event

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
    reference_image: str | None = None  # organic: uploaded file_id
    constraints: dict[str, Any] | None = None  # organic: {bounding_box, engineering_cuts}
    parent_job_id: str | None = None  # fork: link to parent (text only)
    pipeline_config: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    """Job 创建响应。"""

    job_id: str
    status: str


class CorrectionItem(BaseModel):
    """单条用户修正记录（内联于 JobDetailResponse）。"""

    field_path: str
    original_value: str
    corrected_value: str
    timestamp: str | None = None
    id: int | None = None


class JobDetailResponse(BaseModel):
    """Job 详情响应。

    包含与旧版 history.py get_job_detail 相同的完整字段集。
    """

    job_id: str
    status: str
    input_type: str
    input_text: str
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    printability: dict[str, Any] | None = None
    # 以下字段与旧版 history.py 对齐
    intent: dict[str, Any] | None = None
    precise_spec: dict[str, Any] | None = None
    drawing_spec: dict[str, Any] | None = None
    drawing_spec_confirmed: dict[str, Any] | None = None
    image_path: str | None = None
    organic_spec: dict[str, Any] | None = None
    generated_code: str | None = None
    parent_job_id: str | None = None
    child_job_ids: list[str] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    corrections: list[CorrectionItem] = Field(default_factory=list)


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
    pipeline_config_updates: dict[str, dict] | None = None


class RegenerateResponse(BaseModel):
    """重新生成响应。"""

    job_id: str
    cloned_from: str
    status: str


# ---------------------------------------------------------------------------
# Job 详情转换
# ---------------------------------------------------------------------------


def _job_to_detail(
    job: Job,
    corrections: list[CorrectionItem] | None = None,
    child_job_ids: list[str] | None = None,
    *,
    include_code: bool = True,
) -> JobDetailResponse:
    """将 Job Pydantic 模型转换为 API 响应。"""
    intent_data: dict[str, Any] | None = None
    if job.intent is not None:
        intent_data = (
            job.intent.model_dump(mode="json")
            if hasattr(job.intent, "model_dump")
            else job.intent
        )

    precise_data: dict[str, Any] | None = None
    if job.precise_spec is not None:
        precise_data = (
            job.precise_spec.model_dump(mode="json")
            if hasattr(job.precise_spec, "model_dump")
            else job.precise_spec
        )

    return JobDetailResponse(
        job_id=job.job_id,
        status=job.status.value,
        input_type=job.input_type,
        input_text=job.input_text,
        result=job.result,
        printability=job.printability,
        error=job.error,
        created_at=job.created_at,
        intent=intent_data,
        precise_spec=precise_data,
        drawing_spec=job.drawing_spec,
        drawing_spec_confirmed=job.drawing_spec_confirmed,
        image_path=job.image_path,
        organic_spec=job.organic_spec,
        generated_code=job.generated_code if include_code else None,
        parent_job_id=job.parent_job_id,
        child_job_ids=child_job_ids or [],
        recommendations=job.recommendations,
        corrections=corrections or [],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — 统一创建（返回 SSE 流）
# ---------------------------------------------------------------------------


@router.post("")
async def create_job_endpoint(body: CreateJobRequest, request: Request) -> EventSourceResponse:
    """创建新 Job，按 input_type 分发管道，返回 SSE 事件流。"""
    if body.input_type == "drawing":
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message="图纸模式请使用 POST /api/v1/jobs/upload（需上传图片文件）",
        )
    if body.input_type not in ("text", "organic"):
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"不支持的 input_type: {body.input_type!r}，可选值: text | organic | drawing",
        )

    # Fork validation: parent_job_id only supported for text
    if body.parent_job_id and body.input_type != "text":
        raise APIError(
            status_code=400,
            code=ErrorCode.VALIDATION_FAILED,
            message="Fork is only supported for text jobs",
        )

    # Verify parent job exists in DB
    if body.parent_job_id:
        from backend.db.database import async_session
        from backend.db.repository import get_job as repo_get_job

        async with async_session() as session:
            parent = await repo_get_job(session, body.parent_job_id)
        if parent is None:
            raise APIError(
                status_code=404,
                code=ErrorCode.JOB_NOT_FOUND,
                message=f"Parent job not found: {body.parent_job_id}",
            )

    # Organic mode: feature gate + input validation
    if body.input_type == "organic":
        from backend.config import Settings
        settings = Settings()
        if not settings.organic_enabled:
            raise APIError(
                status_code=503,
                code=ErrorCode.ORGANIC_DISABLED,
                message="Organic engine is disabled. Set ORGANIC_ENABLED=true to enable.",
            )
        input_text = body.text or body.prompt
        if not input_text and not body.reference_image:
            raise APIError(
                status_code=422,
                code=ErrorCode.VALIDATION_FAILED,
                message="organic 模式需要提供文本描述 (text/prompt) 或参考图 (reference_image)",
            )

    job_id = str(uuid.uuid4())
    input_text = body.text or body.prompt
    cad_graph = request.app.state.cad_graph
    config = {"configurable": {"thread_id": job_id}}

    # Parse pipeline_config — resolve presets into full config dict
    from backend.models.pipeline_config import PRESETS, PipelineConfig

    pc_raw = body.pipeline_config
    if isinstance(pc_raw, dict) and pc_raw:
        preset = pc_raw.get("preset", "balanced")
        if preset in PRESETS and len(pc_raw) <= 2:
            pc = PRESETS[preset]
        else:
            pc = PipelineConfig(**pc_raw)
    else:
        pc = PRESETS["balanced"]

    # Build initial_state
    from backend.graph.compat import convert_legacy_pipeline_config, is_legacy_format
    from backend.graph.presets import parse_pipeline_config

    pc_dict = pc.model_dump()
    if is_legacy_format(pc_dict):
        new_pc = convert_legacy_pipeline_config(pc_dict)
    else:
        new_pc = parse_pipeline_config(dict(pc_dict))

    initial_state: dict[str, Any] = {
        "job_id": job_id,
        "input_type": body.input_type,
        "input_text": input_text,
        "image_path": None,
        "pipeline_config": new_pc,
        "status": "pending",
        "assets": {},
        "data": {},
        "node_trace": [],
    }

    if body.parent_job_id:
        initial_state["parent_job_id"] = body.parent_job_id

    # Map organic-specific fields to initial state
    if body.input_type == "organic":
        initial_state["organic_provider"] = body.provider
        initial_state["organic_quality_mode"] = body.quality_mode
        initial_state["organic_reference_image"] = body.reference_image
        initial_state["organic_constraints"] = body.constraints

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        async for event in cad_graph.astream_events(initial_state, config=config, version="v2"):
            if event["event"] == "on_custom_event":
                emit_event(job_id, event["name"], event["data"])
                yield _sse(event["name"], event["data"])

    return EventSourceResponse(event_stream())


@router.post("/upload")
async def create_drawing_job(
    image: UploadFile = File(...),
    pipeline_config: str = Form("{}"),
    request: Request = None,  # type: ignore[assignment]  # FastAPI injects
) -> EventSourceResponse:
    """创建图纸模式 Job（multipart 上传），返回 SSE 事件流。"""
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
    job_dir = ensure_job_dir(job_id)
    ext = Path(image.filename or "input.png").suffix or ".png"
    image_path = str(job_dir / f"input{ext}")
    await asyncio.to_thread(Path(image_path).write_bytes, content)

    # Parse pipeline_config for drawing upload
    from backend.models.pipeline_config import PRESETS, PipelineConfig, _parse_pipeline_config

    pc = _parse_pipeline_config(pipeline_config)

    cad_graph = request.app.state.cad_graph
    config = {"configurable": {"thread_id": job_id}}

    # Convert pipeline_config
    from backend.graph.compat import convert_legacy_pipeline_config, is_legacy_format
    from backend.graph.presets import parse_pipeline_config

    pc_dict = pc.model_dump()
    if is_legacy_format(pc_dict):
        pipeline_cfg = convert_legacy_pipeline_config(pc_dict)
    else:
        pipeline_cfg = parse_pipeline_config(dict(pc_dict))

    initial_state: dict[str, Any] = {
        "job_id": job_id,
        "input_type": "drawing",
        "input_text": None,
        "image_path": image_path,
        "pipeline_config": pipeline_cfg,
        "status": "pending",
        "assets": {},
        "data": {},
        "node_trace": [],
    }

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        async for event in cad_graph.astream_events(initial_state, config=config, version="v2"):
            if event["event"] == "on_custom_event":
                emit_event(job_id, event["name"], event["data"])
                yield _sse(event["name"], event["data"])

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

    items = [_job_to_detail(_orm_to_job(j), include_code=False) for j in orm_jobs]
    return JobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/organic-providers — 有机 Provider 健康状态
# (Must be before /{job_id} to avoid route parameter conflict)
# ---------------------------------------------------------------------------

_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MIME_TO_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


@router.get("/organic-providers")
async def get_organic_providers() -> dict[str, Any]:
    """Check health of available mesh generation providers."""
    from backend.config import Settings
    from backend.infra.mesh_providers import HunyuanProvider, TripoProvider

    settings = Settings()
    if not settings.organic_enabled:
        raise APIError(
            status_code=503,
            code=ErrorCode.ORGANIC_DISABLED,
            message="Organic engine is disabled.",
        )

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
# POST /api/v1/jobs/upload-reference — 参考图上传
# ---------------------------------------------------------------------------


@router.post("/upload-reference")
async def upload_reference_image(
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a reference image for organic generation."""
    from backend.config import Settings

    settings = Settings()
    if not settings.organic_enabled:
        raise APIError(
            status_code=503,
            code=ErrorCode.ORGANIC_DISABLED,
            message="Organic engine is disabled.",
        )

    if file.content_type not in _ALLOWED_MIME_TYPES:
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(sorted(_ALLOWED_MIME_TYPES))}",
        )

    max_bytes = settings.organic_upload_max_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise APIError(
            status_code=422,
            code=ErrorCode.VALIDATION_FAILED,
            message=f"File too large: {len(content)} bytes. Maximum: {max_bytes} bytes ({settings.organic_upload_max_mb}MB)",
        )

    upload_dir = Path("outputs") / "organic" / "uploads"
    file_id = str(uuid.uuid4())
    ext = Path(file.filename or "image.png").suffix or _MIME_TO_EXT.get(file.content_type or "", ".png")
    save_path = upload_dir / f"{file_id}{ext}"

    def _write_upload() -> None:
        upload_dir.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(content)

    await asyncio.to_thread(_write_upload)

    return {"file_id": file_id, "filename": file.filename or "", "size": len(content)}


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id} — 详情
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_model=JobDetailResponse)
async def get_job_endpoint(job_id: str) -> JobDetailResponse:
    """返回 Job 详情（含用户修正记录）。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    # 查询 corrections + child_job_ids
    from backend.db.database import async_session
    from backend.db.repository import list_child_job_ids, list_corrections_by_job

    corrections_list: list[CorrectionItem] = []
    child_ids: list[str] = []
    async with async_session() as session:
        db_corrections = await list_corrections_by_job(session, job_id)
        child_ids = await list_child_job_ids(session, job_id)

    if db_corrections:
        corrections_list = [
            CorrectionItem(
                id=c.id,
                field_path=c.field_path,
                original_value=c.original_value,
                corrected_value=c.corrected_value,
                timestamp=c.timestamp.isoformat() if c.timestamp else None,
            )
            for c in db_corrections
        ]
    else:
        # JSON 文件兜底（兼容迁移前数据）
        try:
            from backend.core.correction_tracker import load_corrections

            json_corrections = load_corrections(job_id)
            if json_corrections:
                corrections_list = [
                    CorrectionItem(
                        field_path=c.get("field_path", ""),
                        original_value=c.get("original_value", ""),
                        corrected_value=c.get("corrected_value", ""),
                    )
                    for c in json_corrections
                ]
        except Exception:
            pass  # Corrupt file — return empty corrections

    return _job_to_detail(job, corrections=corrections_list, child_job_ids=child_ids)


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
async def confirm_job(job_id: str, body: ConfirmRequest, request: Request) -> EventSourceResponse:
    """确认 AI 分析结果，恢复管道执行，返回 SSE 事件流。"""
    from langgraph.types import Command

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

    # Corrections dual-write (keep existing logic — JSON + DB)
    if body.confirmed_spec and job.drawing_spec:
        try:
            from backend.core.correction_tracker import (
                compute_corrections,
                persist_corrections,
            )
            from backend.db.database import async_session
            from backend.db.repository import create_correction

            corrections = compute_corrections(job.drawing_spec, body.confirmed_spec, job_id)
            if corrections:
                await asyncio.to_thread(persist_corrections, job_id, corrections)
                async with async_session() as _sess:
                    for c in corrections:
                        await create_correction(
                            _sess,
                            job_id=job_id,
                            field_path=c["field_path"],
                            original_value=c["original_value"],
                            corrected_value=c["corrected_value"],
                        )
                    await _sess.commit()
        except Exception as _corr_exc:
            from loguru import logger
            logger.warning("Corrections persistence failed for job {}: {}", job_id, _corr_exc)

    # Drawing mode: validate disclaimer
    is_drawing_mode = job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
    if is_drawing_mode and not body.disclaimer_accepted:
        raise APIError(
            status_code=400,
            code=ErrorCode.VALIDATION_FAILED,
            message="免责声明必须接受后方可继续生成",
        )

    cad_graph = request.app.state.cad_graph
    config = {"configurable": {"thread_id": job_id}}

    is_organic = job.input_type == "organic"

    # Wrap confirm data inside data dict for NodeContext
    resume_data: dict[str, Any] = {
        "data": {
            "confirmed_params": body.confirmed_params,
            "confirmed_spec": body.confirmed_spec,
            "disclaimer_accepted": body.disclaimer_accepted,
        },
    }
    # Validate and include pipeline config updates
    if body.pipeline_config_updates is not None:
        from backend.graph.discovery import discover_nodes
        from backend.graph.registry import registry
        from backend.graph.resolver import DependencyResolver

        discover_nodes()
        # Job model doesn't store pipeline_config; start from empty baseline.
        # The resolver validates topology regardless of baseline.
        merged_config: dict[str, dict] = {}
        for node_name, updates in body.pipeline_config_updates.items():
            merged_config.setdefault(node_name, {}).update(updates)
        try:
            resolved = DependencyResolver.resolve(
                registry, merged_config, job.input_type, include_disabled=False,
            )
            if not resolved.ordered_nodes:
                raise APIError(
                    status_code=400,
                    code=ErrorCode.VALIDATION_FAILED,
                    message="pipeline_config_updates 无效：至少需要启用一个节点",
                )
        except (ValueError, KeyError, TypeError) as exc:
            raise APIError(
                status_code=400,
                code=ErrorCode.VALIDATION_FAILED,
                message=f"pipeline_config_updates 验证失败: {exc}",
            ) from exc
        resume_data["pipeline_config_updates"] = body.pipeline_config_updates

    if is_organic and body.confirmed_spec:
        spec_overrides = body.confirmed_spec
        if "quality_mode" in spec_overrides:
            resume_data["data"]["organic_quality_mode"] = spec_overrides["quality_mode"]
        if "provider" in spec_overrides:
            resume_data["data"]["organic_provider"] = spec_overrides["provider"]

    async def event_stream() -> AsyncGenerator[dict[str, str], None]:
        async for event in cad_graph.astream_events(
            Command(resume=resume_data),
            config=config,
            version="v2",
        ):
            if event["event"] == "on_custom_event":
                emit_event(job_id, event["name"], event["data"])
                yield _sse(event["name"], event["data"])

    return EventSourceResponse(event_stream())


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
# GET /api/v1/jobs/{job_id}/code — 生成代码
# ---------------------------------------------------------------------------


@router.get("/{job_id}/code")
async def get_job_code(job_id: str) -> dict[str, Any]:
    """返回 Job 的生成代码（可能较大，独立端点减轻列表负载）。"""
    job = await get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return {"job_id": job_id, "generated_code": job.generated_code}


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{job_id}/corrections — 用户修正记录
# ---------------------------------------------------------------------------


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
