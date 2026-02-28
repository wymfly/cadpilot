"""E2E 9.5: 数据持久化测试。

创建 Job → 重新初始化 DB → 查询数据完整 → 零件库展示

SQLite 文件持久化确保数据在「重启」后保持完整。
测试通过重建 session/engine 模拟应用重启。
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


class TestDataPersistence:
    """数据持久化 E2E 验证。"""

    async def test_job_survives_db_reinit(self, client: TestClient) -> None:
        """Job 数据在 init_db() 重新调用后保持完整。"""
        # 1. 创建 Job 并设置为完成状态
        await create_job("persist-1", input_type="text", input_text="持久化测试")
        await update_job(
            "persist-1",
            status=JobStatus.COMPLETED,
            result={"message": "生成完成"},
        )

        # 2. 重新调用 init_db (模拟重启)
        from backend.db.database import init_db
        await init_db()

        # 3. 查询 Job — 数据应该完整
        job = await get_job("persist-1")
        assert job is not None
        assert job.job_id == "persist-1"
        assert job.input_text == "持久化测试"
        assert job.status == JobStatus.COMPLETED
        assert job.result == {"message": "生成完成"}

    async def test_multiple_jobs_persist(self, client: TestClient) -> None:
        """多个 Job 在重新初始化后全部保留。"""
        for i in range(5):
            await create_job(
                f"mp-{i}", input_type="text", input_text=f"test-{i}",
            )
            if i % 2 == 0:
                await update_job(f"mp-{i}", status=JobStatus.COMPLETED)

        # 重新初始化
        from backend.db.database import init_db
        await init_db()

        # 验证全部存在
        for i in range(5):
            job = await get_job(f"mp-{i}")
            assert job is not None
            assert job.input_text == f"test-{i}"

    async def test_library_shows_persisted_jobs(
        self, client: TestClient,
    ) -> None:
        """重新初始化后零件库 API 正常展示数据。"""
        await create_job("lib-p1", input_type="text", input_text="法兰盘")
        await update_job("lib-p1", status=JobStatus.COMPLETED)
        await create_job("lib-p2", input_type="drawing")
        await update_job("lib-p2", status=JobStatus.COMPLETED)

        # 重新初始化
        from backend.db.database import init_db
        await init_db()

        # 通过 API 查询
        resp = client.get("/api/v1/jobs?status=completed")
        data = resp.json()
        assert data["total"] >= 2
        ids = [item["job_id"] for item in data["items"]]
        assert "lib-p1" in ids
        assert "lib-p2" in ids

    async def test_job_with_complex_result_persists(
        self, client: TestClient,
    ) -> None:
        """包含复杂 result + printability 的 Job 数据完整持久化。"""
        complex_result = {
            "message": "生成完成",
            "model_url": "/outputs/complex-1/model.glb",
            "step_path": "outputs/complex-1/model.step",
            "confirmed_params": {
                "outer_diameter": 100.0,
                "inner_diameter": 50.0,
                "thickness": 15.0,
            },
        }
        printability = {
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
        }
        await create_job("complex-1", input_type="text", input_text="法兰盘")
        await update_job(
            "complex-1",
            status=JobStatus.COMPLETED,
            result=complex_result,
            printability_result=printability,
        )

        # 重新初始化
        from backend.db.database import init_db
        await init_db()

        job = await get_job("complex-1")
        assert job is not None
        assert job.result is not None
        assert job.result["confirmed_params"]["outer_diameter"] == 100.0

    async def test_drawing_spec_persists(self, client: TestClient) -> None:
        """图纸模式的 drawing_spec 和 confirmed_spec 数据持久化。"""
        original_spec = {"part_type": "rotational", "overall_dimensions": {"d": 50.0}}
        confirmed_spec = {"part_type": "rotational", "overall_dimensions": {"d": 55.0}}

        await create_job("draw-p1", input_type="drawing")
        await update_job(
            "draw-p1",
            drawing_spec=original_spec,
            drawing_spec_confirmed=confirmed_spec,
            status=JobStatus.COMPLETED,
        )

        from backend.db.database import init_db
        await init_db()

        job = await get_job("draw-p1")
        assert job is not None
        assert job.drawing_spec == original_spec
        assert job.drawing_spec_confirmed == confirmed_spec

    async def test_corrections_persist(self, client: TestClient) -> None:
        """用户修正记录在重新初始化后保持完整。"""
        await create_job("corr-p1", input_type="drawing")

        from backend.db.database import async_session
        from backend.db.repository import create_correction

        async with async_session() as session:
            await create_correction(
                session,
                job_id="corr-p1",
                field_path="overall_dimensions.diameter",
                original_value="50.0",
                corrected_value="55.0",
            )
            await session.commit()

        # 重新初始化
        from backend.db.database import init_db
        await init_db()

        # 通过 API 查询
        resp = client.get("/api/v1/jobs/corr-p1/corrections")
        assert resp.status_code == 200
        corrections = resp.json()
        assert len(corrections) == 1
        assert corrections[0]["field_path"] == "overall_dimensions.diameter"
