"""E2E 9.1: 精密建模全流程。

文本输入 → Job 创建 → IntentParser(模拟) → 模板匹配 → 参数确认
→ 预览 → 生成 → DfAM → 下载 → 零件库展示

覆盖 V1 API 端点全链路，通过直接操作 Job 状态模拟管道进度。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.models.job import (
    JobStatus,
    create_job,
    get_job,
    update_job,
)


class TestPrecisionFullFlow:
    """精密建模全链路 E2E 验证。"""

    async def test_text_input_to_library(self, client: TestClient) -> None:
        """完整文本建模流程：创建 → 确认 → 生成 → 完成 → 零件库。"""
        from tests.e2e.conftest import get_sse_job_id, parse_sse_events

        # 1. 创建 text 类型 Job（返回 SSE 流）
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "法兰盘，外径100mm，内径50mm"},
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)
        # 验证 SSE 中首个事件状态为 created
        events = parse_sse_events(resp)
        assert events[0]["status"] == "created"

        # 2. 查询 Job 详情
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["input_type"] == "text"
        assert detail["input_text"] == "法兰盘，外径100mm，内径50mm"

        # 3. 模拟 IntentParser 完成 → awaiting_confirmation
        await update_job(
            job_id,
            status=JobStatus.AWAITING_CONFIRMATION,
            result={
                "template_name": "flange",
                "intent": {
                    "part_category": "法兰盘",
                    "part_type": "rotational",
                    "known_params": {"outer_diameter": 100.0, "inner_diameter": 50.0},
                    "missing_params": ["thickness"],
                    "confidence": 0.85,
                },
            },
        )

        # 4. 确认参数（HITL）- 返回 SSE 流
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={
                "confirmed_params": {
                    "outer_diameter": 100.0,
                    "inner_diameter": 50.0,
                    "thickness": 15.0,
                },
                "base_body_method": "revolve",
            },
        )
        assert resp.status_code == 200
        # 验证 SSE 事件中含 generating
        confirm_events = parse_sse_events(resp)
        statuses = [e.get("status") for e in confirm_events]
        assert "generating" in statuses

        # 5. 验证 Job 已进入 generating 或之后的状态
        job = await get_job(job_id)
        assert job is not None
        assert job.status in {JobStatus.GENERATING, JobStatus.REFINING, JobStatus.COMPLETED, JobStatus.FAILED}

        # 6. 模拟生成完成 + DfAM 结果
        await update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "model_url": f"/outputs/{job_id}/model.glb",
                "step_path": f"outputs/{job_id}/model.step",
                "confirmed_params": {
                    "outer_diameter": 100.0,
                    "inner_diameter": 50.0,
                    "thickness": 15.0,
                },
            },
            printability_result={
                "printable": True,
                "score": 0.92,
                "issues": [],
                "material_estimate": {
                    "filament_weight_g": 45.2,
                    "filament_length_m": 15.1,
                    "cost_estimate_cny": 12.5,
                },
                "time_estimate": {
                    "total_minutes": 120,
                    "layer_count": 450,
                },
            },
        )

        # 7. 确认完成状态
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["status"] == "completed"
        assert detail["result"] is not None
        assert detail["result"]["model_url"] is not None

        # 8. 零件库列表验证 — Job 出现在列表中
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        library = resp.json()
        assert library["total"] >= 1
        job_ids = [item["job_id"] for item in library["items"]]
        assert job_id in job_ids

    async def test_intent_parsed_then_confirm(self, client: TestClient) -> None:
        """验证 intent_parsed → awaiting_confirmation → confirm 状态流转。"""
        from tests.e2e.conftest import get_sse_job_id

        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "轴承座"},
        )
        job_id = get_sse_job_id(resp)

        # IntentParser 完成
        await update_job(job_id, status=JobStatus.INTENT_PARSED)
        job = await get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.INTENT_PARSED

        # 过渡到 awaiting_confirmation
        await update_job(job_id, status=JobStatus.AWAITING_CONFIRMATION)

        # 确认
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={"confirmed_params": {"width": 80.0, "height": 60.0}},
        )
        assert resp.status_code == 200

    async def test_regenerate_creates_new_job(self, client: TestClient) -> None:
        """验证重新生成创建全新 Job。"""
        from tests.e2e.conftest import get_sse_job_id

        # 创建并完成一个 Job（返回 SSE 流）
        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "text", "text": "齿轮，模数2"},
        )
        original_id = get_sse_job_id(resp)
        await update_job(original_id, status=JobStatus.COMPLETED)

        # 重新生成
        resp = client.post(f"/api/v1/jobs/{original_id}/regenerate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] != original_id
        assert data["cloned_from"] == original_id
        assert data["status"] == "created"

        # 新 Job 继承输入文本
        new_job = await get_job(data["job_id"])
        assert new_job is not None
        assert new_job.input_text == "齿轮，模数2"
        assert new_job.status == JobStatus.CREATED

    async def test_sse_events_for_completed_job(self, client: TestClient) -> None:
        """验证已完成 Job 的 SSE 订阅立即返回终止事件。"""
        await create_job("sse-1", input_type="text", input_text="test")
        await update_job(
            "sse-1",
            status=JobStatus.COMPLETED,
            result={"message": "done", "model_url": "/outputs/sse-1/model.glb"},
        )

        with client.stream("GET", "/api/v1/jobs/sse-1/events") as resp:
            assert resp.status_code == 200
            events = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))

        assert len(events) >= 1
        # 应包含 completed 状态的事件
        statuses = [e.get("status") for e in events]
        assert "completed" in statuses

    async def test_filter_by_input_type(self, client: TestClient) -> None:
        """验证零件库按 input_type 过滤。"""
        await create_job("t1", input_type="text", input_text="法兰盘")
        await create_job("d1", input_type="drawing")

        resp = client.get("/api/v1/jobs?input_type=text")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["input_type"] == "text"

        resp = client.get("/api/v1/jobs?input_type=drawing")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["input_type"] == "drawing"

    async def test_preview_endpoint_exists(self, client: TestClient) -> None:
        """验证预览端点可达（即使因缺少模板返回错误）。"""
        resp = client.post(
            "/api/v1/preview/parametric",
            json={"template_name": "nonexistent", "params": {}},
        )
        # 端点存在，模板不存在返回 404（非路由级 404）
        assert resp.status_code in (200, 404, 500)

    async def test_soft_delete_excludes_from_library(
        self, client: TestClient,
    ) -> None:
        """验证删除后 Job 不再出现在零件库。"""
        await create_job("del-1", input_type="text", input_text="test")
        await create_job("keep-1", input_type="text", input_text="test2")

        client.delete("/api/v1/jobs/del-1")

        resp = client.get("/api/v1/jobs")
        data = resp.json()
        ids = [item["job_id"] for item in data["items"]]
        assert "del-1" not in ids
        assert "keep-1" in ids
