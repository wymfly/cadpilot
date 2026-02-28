"""E2E 9.2: 图纸路径全流程。

图纸上传 → Job 创建 → DrawingAnalyzer(模拟) → HITL 表单确认(含修改)
→ 生成 → DfAM → user_corrections 验证

覆盖图纸模式下的 V1 API 全链路。
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


class TestDrawingFullFlow:
    """图纸建模全链路 E2E 验证。"""

    async def test_drawing_upload_to_completion(
        self, client: TestClient,
    ) -> None:
        """完整图纸流程：上传 → 分析 → 确认(含修改) → 生成 → 完成。"""
        # 1. 上传图纸
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/v1/jobs/upload",
            files={"image": ("drawing.png", fake_png, "image/png")},
            data={"pipeline_config": "{}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        job_id = data["job_id"]
        assert data["status"] == "created"

        # 2. 验证 Job 详情
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["input_type"] == "drawing"

        # 3. 模拟 DrawingAnalyzer 完成 → 存储原始 drawing_spec
        original_spec = {
            "part_type": "rotational",
            "description": "阶梯轴",
            "overall_dimensions": {
                "total_length": 120.0,
                "max_diameter": 40.0,
            },
            "base_body": {
                "method": "revolve",
                "width": 40.0,
                "length": 120.0,
            },
            "features": [
                {"type": "chamfer", "size": 1.0, "location": "端面"},
            ],
            "notes": ["材质: 45钢"],
        }
        await update_job(
            job_id,
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=original_spec,
        )

        # 4. 用户修改 spec 后确认（修改了 total_length 和 max_diameter）
        confirmed_spec = {
            "part_type": "rotational",
            "description": "阶梯轴",
            "overall_dimensions": {
                "total_length": 125.0,  # 用户修改: 120 → 125
                "max_diameter": 42.0,   # 用户修改: 40 → 42
            },
            "base_body": {
                "method": "revolve",
                "width": 42.0,
                "length": 125.0,
            },
            "features": [
                {"type": "chamfer", "size": 1.5, "location": "端面"},  # 修改
            ],
            "notes": ["材质: 45钢"],
        }
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={
                "confirmed_spec": confirmed_spec,
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "confirmed"

        # 5. 验证 Job 已进入 generating 状态
        job = await get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.GENERATING

        # 6. 验证确认后的 spec 已保存
        assert job.drawing_spec_confirmed is not None
        assert job.drawing_spec_confirmed["overall_dimensions"]["total_length"] == 125.0

        # 7. 模拟生成完成 + DfAM 结果
        await update_job(
            job_id,
            status=JobStatus.COMPLETED,
            result={
                "message": "生成完成",
                "model_url": f"/outputs/{job_id}/model.glb",
                "step_path": f"outputs/{job_id}/model.step",
                "confirmed_spec": confirmed_spec,
            },
            printability_result={
                "printable": True,
                "score": 0.88,
                "issues": [{"severity": "warning", "message": "悬垂角度偏大"}],
            },
        )

        # 8. 验证完成状态
        resp = client.get(f"/api/v1/jobs/{job_id}")
        detail = resp.json()
        assert detail["status"] == "completed"
        assert detail["result"]["model_url"] is not None

    async def test_drawing_confirm_wrong_state_rejected(
        self, client: TestClient,
    ) -> None:
        """未进入 awaiting_drawing_confirmation 状态时，确认应被拒绝。"""
        resp = client.post(
            "/api/v1/jobs/upload",
            files={"image": ("test.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        job_id = resp.json()["job_id"]

        # 直接尝试确认（状态仍为 created）
        resp = client.post(
            f"/api/v1/jobs/{job_id}/confirm",
            json={"confirmed_spec": {"part_type": "plate"}},
        )
        assert resp.status_code == 409

    async def test_corrections_tracking(self, client: TestClient) -> None:
        """验证用户修正数据通过 corrections 端点可查。"""
        await create_job("corr-1", input_type="drawing")

        # 写入修正数据
        from backend.db.database import async_session
        from backend.db.repository import create_correction

        async with async_session() as session:
            await create_correction(
                session,
                job_id="corr-1",
                field_path="overall_dimensions.diameter",
                original_value="50.0",
                corrected_value="55.0",
            )
            await create_correction(
                session,
                job_id="corr-1",
                field_path="features[0].size",
                original_value="1.0",
                corrected_value="1.5",
            )
            await session.commit()

        # 查询修正记录
        resp = client.get("/api/v1/jobs/corr-1/corrections")
        assert resp.status_code == 200
        corrections = resp.json()
        assert len(corrections) == 2

        paths = [c["field_path"] for c in corrections]
        assert "overall_dimensions.diameter" in paths
        assert "features[0].size" in paths

    async def test_drawing_spec_preserved_after_confirm(
        self, client: TestClient,
    ) -> None:
        """验证原始 drawing_spec 和确认后的 spec 都被保留。"""
        await create_job("spec-1", input_type="drawing")
        original = {"part_type": "plate", "overall_dimensions": {"width": 100.0}}
        await update_job(
            "spec-1",
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=original,
        )

        confirmed = {"part_type": "plate", "overall_dimensions": {"width": 105.0}}
        resp = client.post(
            "/api/v1/jobs/spec-1/confirm",
            json={"confirmed_spec": confirmed},
        )
        assert resp.status_code == 200

        job = await get_job("spec-1")
        assert job is not None
        # 原始 spec 保留
        assert job.drawing_spec["overall_dimensions"]["width"] == 100.0
        # 确认后的 spec 独立保存
        assert job.drawing_spec_confirmed["overall_dimensions"]["width"] == 105.0

    async def test_drawing_in_library(self, client: TestClient) -> None:
        """验证图纸生成的 Job 出现在零件库列表。"""
        await create_job("lib-d1", input_type="drawing")
        await update_job(
            "lib-d1",
            status=JobStatus.COMPLETED,
            result={"message": "done"},
        )

        resp = client.get("/api/v1/jobs?status=completed")
        data = resp.json()
        assert data["total"] >= 1
        ids = [item["job_id"] for item in data["items"]]
        assert "lib-d1" in ids
