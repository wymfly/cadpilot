"""E2E 测试共享 fixtures。

所有 E2E 测试共享：
- 数据库初始化/清理
- FastAPI TestClient
- 常用辅助函数（含 SSE 解析）
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.models.job import clear_jobs


# ---------------------------------------------------------------------------
# SSE 解析助手
# ---------------------------------------------------------------------------


def parse_sse_events(resp) -> list[dict]:
    """从响应文本中解析所有 SSE data 事件，返回已解析 dict 列表。"""
    events = []
    for line in resp.text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str:
                try:
                    events.append(json.loads(data_str))
                except Exception:
                    pass
    return events


def get_sse_job_id(resp) -> str:
    """从 SSE 响应的首个事件中提取 job_id。"""
    for event in parse_sse_events(resp):
        if "job_id" in event:
            return event["job_id"]
    raise ValueError(f"SSE 响应中找不到 job_id: {resp.text[:200]}")


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
    """创建 FastAPI TestClient 实例（含 LangGraph 初始化）。"""
    from backend.main import app

    # TestClient 不经过 lifespan，需手动初始化 cad_graph
    import asyncio

    from backend.graph import get_compiled_graph

    loop = asyncio.get_event_loop()
    app.state.cad_graph = loop.run_until_complete(get_compiled_graph(None))

    return TestClient(app)
