"""E2E 9.3: 创意雕塑全流程。

描述输入 → Job 创建(V1) → 约束设置 → 管道模拟 → DfAM → 零件库

V1 API 支持 organic input_type 的 Job 创建和生命周期管理。
实际 mesh 生成通过旧版 /api/generate/organic 端点（本测试不覆盖）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.models.job import (
    JobStatus,
    create_job,
    get_job,
    update_job,
)


class TestOrganicFullFlow:
    """创意雕塑全链路 E2E 验证。"""

    async def test_organic_job_lifecycle(self, client: TestClient) -> None:
        """Organic Job 完整生命周期: created → generating → completed。"""
        from tests.e2e.conftest import get_sse_job_id, parse_sse_events

        # 1. 通过 V1 API 创建 organic 类型 Job（返回 SSE 流）
        resp = client.post(
            "/api/v1/jobs",
            json={
                "input_type": "organic",
                "prompt": "一条中国龙的雕塑，蜿蜒盘旋",
                "provider": "auto",
                "quality_mode": "standard",
            },
        )
        assert resp.status_code == 200
        job_id = get_sse_job_id(resp)
        events = parse_sse_events(resp)
        # @timed_node emits node.started as first event for create_job
        assert events[0]["node"] == "create_job"

        # 2. 查询 Job 详情
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["input_type"] == "organic"

        # 3. 模拟管道进度：generating
        await update_job(job_id, status=JobStatus.GENERATING)
        job = await get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.GENERATING

        # 4. 模拟后处理完成
        await update_job(job_id, status=JobStatus.REFINING)

        # 5. 模拟完成 + DfAM + 3MF 输出
        await update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "model_url": f"/outputs/organic/{job_id}/model.glb",
                "stl_url": f"/outputs/organic/{job_id}/model.stl",
                "threemf_url": f"/outputs/organic/{job_id}/model.3mf",
                "mesh_stats": {
                    "vertex_count": 15234,
                    "face_count": 30468,
                    "is_watertight": True,
                    "volume_cm3": 125.4,
                },
            },
            printability_result={
                "printable": True,
                "score": 0.78,
                "issues": [
                    {"severity": "info", "message": "建议添加支撑结构"},
                ],
            },
        )

        # 6. 验证完成状态和下载链接
        resp = client.get(f"/api/v1/jobs/{job_id}")
        detail = resp.json()
        assert detail["status"] == "completed"
        assert detail["result"]["model_url"] is not None

        # 7. 零件库列表验证
        resp = client.get("/api/v1/jobs")
        data = resp.json()
        ids = [item["job_id"] for item in data["items"]]
        assert job_id in ids

    async def test_organic_job_failure_handling(
        self, client: TestClient,
    ) -> None:
        """Organic Job 失败场景。"""
        from tests.e2e.conftest import get_sse_job_id

        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "organic", "prompt": "test"},
        )
        job_id = get_sse_job_id(resp)

        # 模拟生成失败
        await update_job(
            job_id,
            status=JobStatus.FAILED,
            error="Mesh provider timeout",
        )

        resp = client.get(f"/api/v1/jobs/{job_id}")
        detail = resp.json()
        assert detail["status"] == "failed"
        assert detail["error"] == "Mesh provider timeout"

    async def test_organic_regenerate(self, client: TestClient) -> None:
        """Organic Job 重新生成。"""
        from tests.e2e.conftest import get_sse_job_id

        resp = client.post(
            "/api/v1/jobs",
            json={"input_type": "organic", "prompt": "猫咪雕像"},
        )
        original_id = get_sse_job_id(resp)
        await update_job(original_id, status=JobStatus.COMPLETED)

        resp = client.post(f"/api/v1/jobs/{original_id}/regenerate")
        assert resp.status_code == 200
        new_data = resp.json()
        assert new_data["job_id"] != original_id
        assert new_data["cloned_from"] == original_id

        new_job = await get_job(new_data["job_id"])
        assert new_job is not None
        assert new_job.input_text == "猫咪雕像"

    async def test_organic_filter_in_library(self, client: TestClient) -> None:
        """验证零件库可按 organic 类型过滤。"""
        await create_job("org-1", input_type="organic", input_text="dragon")
        await create_job("txt-1", input_type="text", input_text="flange")

        resp = client.get("/api/v1/jobs?input_type=organic")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["job_id"] == "org-1"

    async def test_organic_soft_delete(self, client: TestClient) -> None:
        """验证 organic Job 可软删除。"""
        await create_job("org-del", input_type="organic", input_text="test")

        resp = client.delete("/api/v1/jobs/org-del")
        assert resp.status_code == 200

        resp = client.get("/api/v1/jobs")
        ids = [item["job_id"] for item in resp.json()["items"]]
        assert "org-del" not in ids
