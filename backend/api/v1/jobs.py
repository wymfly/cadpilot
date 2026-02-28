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
from typing import Any

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.api.v1.errors import (
    InvalidJobStateError,
    JobNotFoundError,
)
from backend.infra.outputs import ensure_job_dir
from backend.models.job import (
    Job,
    JobStatus,
    create_job,
    get_job,
    update_job,
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

    new_job_id: str
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
        error=job.error,
        created_at=job.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — 统一创建
# ---------------------------------------------------------------------------


@router.post("", response_model=CreateJobResponse)
async def create_job_endpoint(body: CreateJobRequest) -> CreateJobResponse:
    """创建新 Job，按 input_type 分发管道。"""
    job_id = str(uuid.uuid4())

    input_text = body.text or body.prompt
    job = await create_job(job_id, input_type=body.input_type, input_text=input_text)

    return CreateJobResponse(job_id=job.job_id, status=job.status.value)


@router.post("/upload", response_model=CreateJobResponse)
async def create_drawing_job(
    image: UploadFile = File(...),
    pipeline_config: str = Form("{}"),
) -> CreateJobResponse:
    """创建图纸模式 Job（multipart 上传）。"""
    job_id = str(uuid.uuid4())
    job = await create_job(job_id, input_type="drawing")

    # 保存上传图片
    job_dir = ensure_job_dir(job_id)
    ext = Path(image.filename or "input.png").suffix or ".png"
    image_path = str(job_dir / f"input{ext}")
    content = await image.read()
    await asyncio.to_thread(Path(image_path).write_bytes, content)
    await update_job(job_id, image_path=image_path)

    return CreateJobResponse(job_id=job.job_id, status=job.status.value)


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
async def confirm_job(job_id: str, body: ConfirmRequest) -> dict[str, str]:
    """确认 AI 分析结果，恢复管道执行。

    支持 awaiting_confirmation（文本模式）和 awaiting_drawing_confirmation（图纸模式）。
    自动收集用户修正数据（原始 spec vs 确认 spec 的 diff）。
    """
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
            import asyncio

            from backend.core.correction_tracker import (
                compute_corrections,
                persist_corrections,
            )

            corrections = compute_corrections(
                job.drawing_spec, body.confirmed_spec, job_id,
            )
            if corrections:
                await asyncio.to_thread(persist_corrections, job_id, corrections)
        except Exception:
            pass  # 修正收集失败不阻塞主流程

    # 保存确认数据
    update_kwargs: dict[str, Any] = {"status": JobStatus.GENERATING}
    if body.confirmed_spec:
        update_kwargs["drawing_spec_confirmed"] = body.confirmed_spec
    await update_job(job_id, **update_kwargs)

    return {"job_id": job_id, "status": "confirmed"}


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

    return RegenerateResponse(new_job_id=new_job_id, status="created")


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
