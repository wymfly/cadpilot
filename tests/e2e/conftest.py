"""E2E 测试共享 fixtures。

所有 E2E 测试共享：
- 数据库初始化/清理
- FastAPI TestClient
- 常用辅助函数
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.models.job import clear_jobs


@pytest.fixture(autouse=True)
async def _init_and_clean_db():
    """每个测试前重建数据库表，测试后清理数据。"""
    import backend.db.models  # noqa: F401 — 注册 ORM 模型
    from backend.db.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await clear_jobs()


@pytest.fixture()
def client() -> TestClient:
    """创建 FastAPI TestClient 实例。"""
    from backend.main import app

    return TestClient(app)
