"""Tests for Task #2: 数据持久化层。

覆盖：
- Protocol 接口符合性
- SQLiteJobRepository 类方法
- LocalFileStorage 文件操作
- 软删除 (deleted_at)
- Corrections 端点
"""

from __future__ import annotations

import pytest
from backend.models.job import (
    clear_jobs,
    create_job,
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
# Protocol 符合性测试
# ===================================================================


class TestProtocols:
    def test_sqlite_job_repository_implements_protocol(self) -> None:
        """SQLiteJobRepository 应该满足 JobRepository Protocol。"""
        from backend.db.database import async_session
        from backend.db.protocols import JobRepository
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        assert isinstance(repo, JobRepository)

    def test_local_file_storage_implements_protocol(self) -> None:
        """LocalFileStorage 应该满足 FileStorage Protocol。"""
        from backend.db.file_storage import LocalFileStorage
        from backend.db.protocols import FileStorage

        storage = LocalFileStorage("/tmp/test")
        assert isinstance(storage, FileStorage)


# ===================================================================
# SQLiteJobRepository 类测试
# ===================================================================


class TestSQLiteJobRepository:
    async def test_create_and_get(self) -> None:
        from backend.db.database import async_session
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        job = await repo.create("repo-1", input_type="text", input_text="test")
        assert job.job_id == "repo-1"

        fetched = await repo.get("repo-1")
        assert fetched is not None
        assert fetched.input_type == "text"

    async def test_update(self) -> None:
        from backend.db.database import async_session
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        await repo.create("repo-2", input_type="text")
        updated = await repo.update("repo-2", status="generating")
        assert updated.status == "generating"

    async def test_soft_delete(self) -> None:
        from backend.db.database import async_session
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        await repo.create("repo-3", input_type="text")
        await repo.soft_delete("repo-3")

        # get 仍然能找到
        fetched = await repo.get("repo-3")
        assert fetched is not None
        assert fetched.deleted_at is not None

    async def test_soft_deleted_excluded_from_list(self) -> None:
        from backend.db.database import async_session
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        await repo.create("repo-4", input_type="text")
        await repo.create("repo-5", input_type="text")
        await repo.soft_delete("repo-4")

        jobs, total = await repo.list()
        assert total == 1
        assert jobs[0].job_id == "repo-5"

    async def test_list_pagination(self) -> None:
        from backend.db.database import async_session
        from backend.db.repository import SQLiteJobRepository

        repo = SQLiteJobRepository(async_session)
        for i in range(5):
            await repo.create(f"repo-p{i}", input_type="text")

        jobs, total = await repo.list(page=1, page_size=2)
        assert total == 5
        assert len(jobs) == 2


# ===================================================================
# LocalFileStorage 测试
# ===================================================================


class TestLocalFileStorage:
    async def test_save_and_exists(self, tmp_path) -> None:
        from backend.db.file_storage import LocalFileStorage

        storage = LocalFileStorage(tmp_path)
        url = await storage.save("job-1", "model.step", b"step data")
        assert url == "/outputs/job-1/model.step"
        assert await storage.exists("job-1", "model.step")

    async def test_get_path(self, tmp_path) -> None:
        from backend.db.file_storage import LocalFileStorage

        storage = LocalFileStorage(tmp_path)
        path = await storage.get_path("job-1", "model.glb")
        assert "job-1" in path
        assert path.endswith("model.glb")

    async def test_delete(self, tmp_path) -> None:
        from backend.db.file_storage import LocalFileStorage

        storage = LocalFileStorage(tmp_path)
        await storage.save("job-1", "temp.bin", b"data")
        assert await storage.exists("job-1", "temp.bin")

        await storage.delete("job-1", "temp.bin")
        assert not await storage.exists("job-1", "temp.bin")

    async def test_delete_nonexistent_no_error(self, tmp_path) -> None:
        from backend.db.file_storage import LocalFileStorage

        storage = LocalFileStorage(tmp_path)
        await storage.delete("job-1", "nonexistent.bin")  # 不应报错


# ===================================================================
# Corrections 端点测试
# ===================================================================


class TestCorrectionsEndpoint:
    async def test_get_corrections_empty(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test")

        resp = client.get("/api/v1/jobs/j1/corrections")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_corrections_with_data(self, client: TestClient) -> None:
        await create_job("j1", input_type="drawing")

        # 直接插入 correction 数据
        from backend.db.database import async_session
        from backend.db.repository import create_correction

        async with async_session() as session:
            await create_correction(
                session,
                job_id="j1",
                field_path="overall_dimensions.diameter",
                original_value="50.0",
                corrected_value="55.0",
            )
            await session.commit()

        resp = client.get("/api/v1/jobs/j1/corrections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["field_path"] == "overall_dimensions.diameter"
        assert data[0]["original_value"] == "50.0"
        assert data[0]["corrected_value"] == "55.0"

    def test_get_corrections_nonexistent_job(self, client: TestClient) -> None:
        resp = client.get("/api/v1/jobs/nonexistent/corrections")
        assert resp.status_code == 404


# ===================================================================
# 软删除集成测试（通过 API）
# ===================================================================


class TestSoftDeleteIntegration:
    async def test_deleted_job_excluded_from_list(self, client: TestClient) -> None:
        await create_job("j1", input_type="text", input_text="test1")
        await create_job("j2", input_type="text", input_text="test2")

        # 删除 j1
        client.delete("/api/v1/jobs/j1")

        # 列表不应包含 j1（deleted_at 过滤）
        resp = client.get("/api/v1/jobs")
        data = resp.json()
        job_ids = [item["job_id"] for item in data["items"]]
        assert "j1" not in job_ids
        assert "j2" in job_ids
