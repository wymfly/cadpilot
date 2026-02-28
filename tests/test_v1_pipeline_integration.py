"""Tests for Task #3: 后端管道集成。

覆盖：
- PipelineBridge printability_checked 事件
- V1 Preview 端点路由
- HITL 确认 + 用户修正收集
- SSE 事件队列串联
"""

from __future__ import annotations

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
    """初始化数据库并清理。"""
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
# PipelineBridge 事件测试
# ===================================================================


class TestPipelineBridge:
    def test_printability_checked_event(self) -> None:
        """PipelineBridge 应该发送 printability_checked 事件。"""
        from backend.pipeline.sse_bridge import PipelineBridge

        bridge = PipelineBridge(job_id="test-1")
        bridge.printability_checked(result={
            "overall_score": 0.85,
            "printable": True,
        })

        event = bridge.queue.get_nowait()
        assert event["event"] == "printability_checked"
        assert event["data"]["printability"]["overall_score"] == 0.85

    def test_printability_checked_before_complete(self) -> None:
        """printability_checked 事件应在 completed 之前。"""
        from backend.pipeline.sse_bridge import PipelineBridge

        bridge = PipelineBridge(job_id="test-2")
        bridge.printability_checked(result={"printable": True})
        bridge.complete(model_url="/test.glb")

        event1 = bridge.queue.get_nowait()
        event2 = bridge.queue.get_nowait()
        assert event1["event"] == "printability_checked"
        assert event2["event"] == "completed"

    def test_printability_checked_null_result(self) -> None:
        """printability_checked 事件支持 null 结果（检查失败时）。"""
        from backend.pipeline.sse_bridge import PipelineBridge

        bridge = PipelineBridge(job_id="test-3")
        bridge.printability_checked(result=None)

        event = bridge.queue.get_nowait()
        assert event["data"]["printability"] is None


# ===================================================================
# SSE 事件队列测试
# ===================================================================


class TestEventQueue:
    def test_emit_and_consume_event(self) -> None:
        """事件队列应该正确发送和消费事件。"""
        from backend.api.v1.events import cleanup_queue, emit_event, get_event_queue

        emit_event("q-test", "generating", {"message": "生成中..."})

        q = get_event_queue("q-test")
        event = q.get_nowait()
        assert event["event"] == "generating"
        assert event["data"]["message"] == "生成中..."

        cleanup_queue("q-test")


# ===================================================================
# Preview 端点测试
# ===================================================================


class TestPreviewEndpoint:
    def test_preview_endpoint_exists(self, client: TestClient) -> None:
        """V1 preview 端点应该存在。"""
        resp = client.post(
            "/api/v1/preview/parametric",
            json={"template_name": "nonexistent", "params": {}},
        )
        # 应该返回 500（模板不存在）而不是 404（路由不存在）
        assert resp.status_code == 500


# ===================================================================
# HITL 确认流 + 修正收集
# ===================================================================


class TestHITLConfirmWithCorrections:
    async def test_confirm_with_spec_changes(self, client: TestClient) -> None:
        """图纸确认时应收集用户修正。"""
        # 创建 Job 并模拟图纸分析完成
        await create_job("j1", input_type="drawing")
        await update_job(
            "j1",
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec={"overall_dimensions": {"diameter": 100}},
        )

        # 用户确认时修改了参数
        resp = client.post(
            "/api/v1/jobs/j1/confirm",
            json={
                "confirmed_spec": {"overall_dimensions": {"diameter": 120}},
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

        # 验证 Job 已更新
        job = await get_job("j1")
        assert job is not None
        assert job.status == JobStatus.GENERATING
        assert job.drawing_spec_confirmed == {"overall_dimensions": {"diameter": 120}}

    async def test_confirm_text_mode(self, client: TestClient) -> None:
        """文本模式确认不需要 confirmed_spec。"""
        await create_job("j2", input_type="text", input_text="法兰盘")
        await update_job("j2", status=JobStatus.AWAITING_CONFIRMATION)

        resp = client.post(
            "/api/v1/jobs/j2/confirm",
            json={"confirmed_params": {"diameter": 100.0}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"


# ===================================================================
# 完整生命周期测试
# ===================================================================


class TestJobLifecycle:
    async def test_text_job_full_lifecycle(self, client: TestClient) -> None:
        """文本 Job 完整生命周期：创建 → 列表 → 确认 → 详情。"""
        # 创建
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "法兰盘，外径100"},
        )
        job_id = resp.json()["job_id"]

        # 列表
        resp = client.get("/api/v1/jobs")
        assert resp.json()["total"] >= 1

        # 模拟管道推进到 awaiting_confirmation
        await update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)

        # 确认
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={"confirmed_params": {"diameter": 100.0}},
        )
        assert resp.status_code == 200

        # 详情
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.json()["status"] == "generating"

    async def test_drawing_job_full_lifecycle(self, client: TestClient) -> None:
        """图纸 Job 完整生命周期：上传 → 分析 → 确认 → 生成。"""
        # 创建
        resp = client.post(
            "/api/v1/jobs/upload",
            files={"image": ("test.png", b"\x89PNG" + b"\x00" * 100, "image/png")},
        )
        job_id = resp.json()["job_id"]

        # 模拟图纸分析完成
        await update_job(
            job_id,
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec={"part_type": "rotational", "overall_dimensions": {"d": 50}},
        )

        # 确认
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={
                "confirmed_spec": {"part_type": "rotational", "overall_dimensions": {"d": 55}},
            },
        )
        assert resp.status_code == 200

        # 验证修改后的 spec 被保存
        job = await get_job(job_id)
        assert job is not None
        assert job.drawing_spec_confirmed is not None
        assert job.drawing_spec_confirmed["overall_dimensions"]["d"] == 55

    async def test_regenerate_preserves_params(self, client: TestClient) -> None:
        """重新生成应该保留原始参数。"""
        await create_job("orig", input_type="text", input_text="法兰盘")

        resp = client.post("/api/v1/jobs/orig/regenerate")
        assert resp.status_code == 200
        new_id = resp.json()["new_job_id"]

        new_job = await get_job(new_id)
        assert new_job is not None
        assert new_job.input_text == "法兰盘"
        assert new_job.input_type == "text"

    async def test_corrections_endpoint(self, client: TestClient) -> None:
        """corrections 端点应该返回空列表（无修正时）。"""
        await create_job("corr-test", input_type="text")

        resp = client.get("/api/v1/jobs/corr-test/corrections")
        assert resp.status_code == 200
        assert resp.json() == []
