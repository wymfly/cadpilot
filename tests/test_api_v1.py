"""Tests for V1 API — /api/v1/jobs CRUD + SSE events + 统一错误处理。

覆盖场景：
- POST /api/v1/jobs — 创建 text/drawing/organic Job
- GET /api/v1/jobs — 分页列表
- GET /api/v1/jobs/{id} — 详情
- DELETE /api/v1/jobs/{id} — 软删除
- POST /api/v1/jobs/{id}/confirm — HITL 确认
- POST /api/v1/jobs/{id}/regenerate — 重新生成
- GET /api/v1/jobs/{id}/events — SSE 订阅
- 统一错误格式
"""

from __future__ import annotations

import json

import pytest
from backend.models.job import (
    JobStatus,
    clear_jobs,
    create_job,
    get_job,
    update_job,
)
from fastapi.testclient import TestClient

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
async def _init_and_clean_db():
    """初始化数据库并清理 Job 数据。"""
    import backend.db.models  # noqa: F401
    from backend.db.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await clear_jobs()


@pytest.fixture()
def client():
    from backend.main import app

    return TestClient(app)


# ===================================================================
# POST /api/v1/jobs — 创建
# ===================================================================


class TestCreateJob:
    def test_create_text_job(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "法兰盘，外径100mm"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "created"

    def test_create_organic_job(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "organic", "prompt": "一条龙的雕塑"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "created"

    def test_create_drawing_job_via_upload(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/jobs/upload",
            files={"image": ("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
            data={"pipeline_config": "{}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "created"


# ===================================================================
# GET /api/v1/jobs — 列表
# ===================================================================


class TestListJobs:
    async def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_with_jobs(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test1")
        await create_job("j2", input_type="text", input_text="test2")

        resp = client.get("/api/v1/jobs")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_list_pagination(self, client: TestClient) -> None:
        for i in range(5):
            await create_job(f"j{i}", input_type="text", input_text=f"test{i}")

        resp = client.get("/api/v1/jobs?page=1&page_size=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2

    async def test_list_filter_by_status(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test1")
        await create_job("j2", input_type="text", input_text="test2")
        await update_job("j2", status=JobStatus.COMPLETED)

        resp = client.get("/api/v1/jobs?status=completed")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["job_id"] == "j2"


# ===================================================================
# GET /api/v1/jobs/{id} — 详情
# ===================================================================


class TestGetJob:
    async def test_get_existing_job(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="法兰盘")

        resp = client.get("/api/v1/jobs/j1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "j1"
        assert data["input_type"] == "text"
        assert data["input_text"] == "法兰盘"
        assert data["status"] == "created"

    def test_get_nonexistent_job(self, client: TestClient) -> None:
        resp = client.get("/api/v1/jobs/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "JOB_NOT_FOUND"


# ===================================================================
# DELETE /api/v1/jobs/{id} — 软删除
# ===================================================================


class TestDeleteJob:
    async def test_delete_job(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test")

        resp = client.delete("/api/v1/jobs/j1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"

        # 确认 Job 已标记为软删除
        job = await get_job("j1")
        assert job is not None
        assert job.error == "deleted by user"

    def test_delete_nonexistent(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/jobs/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "JOB_NOT_FOUND"


# ===================================================================
# POST /api/v1/jobs/{id}/confirm — HITL 确认
# ===================================================================


class TestConfirmJob:
    async def test_confirm_awaiting_job(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test")
        await update_job("j1", status=JobStatus.AWAITING_CONFIRMATION)

        resp = client.post(
            "/api/v1/jobs/j1/confirm",
            json={"confirmed_params": {"diameter": 100.0}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"

        # 验证状态已变为 generating
        job = await get_job("j1")
        assert job is not None
        assert job.status == JobStatus.GENERATING

    async def test_confirm_wrong_state(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test")

        resp = client.post(
            "/api/v1/jobs/j1/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "INVALID_JOB_STATE"

    def test_confirm_nonexistent(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/jobs/nonexistent/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 404

    async def test_confirm_drawing_mode(self, client: TestClient) -> None:
        await create_job("j1", input_type="drawing")
        await update_job("j1", status=JobStatus.AWAITING_DRAWING_CONFIRMATION)

        resp = client.post(
            "/api/v1/jobs/j1/confirm",
            json={
                "confirmed_spec": {"part_type": "rotational"},
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"


# ===================================================================
# POST /api/v1/jobs/{id}/regenerate — 重新生成
# ===================================================================


class TestRegenerateJob:
    async def test_regenerate_job(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="法兰盘")

        resp = client.post("/api/v1/jobs/j1/regenerate")
        assert resp.status_code == 200
        data = resp.json()
        assert "new_job_id" in data
        assert data["status"] == "created"
        assert data["new_job_id"] != "j1"

        # 验证新 Job 存在
        new_job = await get_job(data["new_job_id"])
        assert new_job is not None
        assert new_job.input_text == "法兰盘"

    def test_regenerate_nonexistent(self, client: TestClient) -> None:
        resp = client.post("/api/v1/jobs/nonexistent/regenerate")
        assert resp.status_code == 404


# ===================================================================
# GET /api/v1/jobs/{id}/events — SSE 订阅
# ===================================================================


class TestJobEvents:
    async def test_sse_completed_job(self, client: TestClient) -> None:
        """已完成的 Job 立即返回 completed 事件。"""
        await create_job("j1", input_type="text", input_text="test")
        await update_job("j1", status=JobStatus.COMPLETED, result={"message": "done"})

        with client.stream("GET", "/api/v1/jobs/j1/events") as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    events.append(data)
            # 应该收到 status + completed 事件
            assert len(events) >= 1

    def test_sse_nonexistent_job(self, client: TestClient) -> None:
        resp = client.get("/api/v1/jobs/nonexistent/events")
        assert resp.status_code == 404


# ===================================================================
# 统一错误格式
# ===================================================================


class TestErrorFormat:
    def test_not_found_error_format(self, client: TestClient) -> None:
        resp = client.get("/api/v1/jobs/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]
        assert data["error"]["code"] == "JOB_NOT_FOUND"

    async def test_state_conflict_error_format(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test")

        resp = client.post(
            "/api/v1/jobs/j1/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "INVALID_JOB_STATE"

    def test_validation_error_format(self, client: TestClient) -> None:
        """POST body 格式错误应返回统一错误格式。"""
        resp = client.post(
            "/api/v1/jobs",
            content="invalid json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_FAILED"
