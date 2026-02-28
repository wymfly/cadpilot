"""Tests for History API endpoints (list, detail, regenerate, delete)."""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.job import clear_jobs


@pytest.fixture(autouse=True)
async def _init_and_clean_jobs():
    """Initialize DB and clear job store before each test."""
    import backend.db.models  # noqa: F401
    from backend.db.database import init_db

    await init_db()
    await clear_jobs()
    yield
    await clear_jobs()


@pytest.fixture
def app():
    from backend.main import app
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_test_job(
    session: Any,
    job_id: str,
    input_type: str = "text",
    input_text: str = "",
    status: str = "completed",
) -> None:
    """Helper to insert a job directly via repository."""
    from backend.db.repository import create_job

    await create_job(
        session,
        job_id=job_id,
        status=status,
        input_type=input_type,
        input_text=input_text,
        recommendations=[],
    )
    await session.commit()


# ---------------------------------------------------------------------------
# List jobs
# ---------------------------------------------------------------------------

class TestListJobs:
    async def test_empty_list(self, client: AsyncClient) -> None:
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_returns_jobs(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "job-1", input_text="gear")
            await _create_test_job(session, "job-2", input_text="plate")

        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    async def test_pagination(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            for i in range(5):
                await _create_test_job(session, f"job-{i}", input_text=f"part-{i}")

        resp = await client.get("/api/jobs?page=1&page_size=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1

        resp2 = await client.get("/api/jobs?page=3&page_size=2")
        data2 = resp2.json()
        assert len(data2["items"]) == 1

    async def test_filter_by_status(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "j-completed", status="completed")
            await _create_test_job(session, "j-failed", status="failed")

        resp = await client.get("/api/jobs?status=completed")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["job_id"] == "j-completed"

    async def test_filter_by_input_type(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "j-text", input_type="text")
            await _create_test_job(session, "j-drawing", input_type="drawing")

        resp = await client.get("/api/jobs?input_type=drawing")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["job_id"] == "j-drawing"


# ---------------------------------------------------------------------------
# Job detail
# ---------------------------------------------------------------------------

class TestJobDetail:
    async def test_get_detail_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404

    async def test_get_detail_returns_full_info(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "detail-1", input_text="齿轮")

        resp = await client.get("/api/jobs/detail-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "detail-1"
        assert data["input_text"] == "齿轮"
        assert "corrections" in data
        assert data["corrections"] == []

    async def test_detail_includes_corrections(self, client: AsyncClient) -> None:
        from backend.db.database import async_session
        from backend.db.repository import create_correction

        async with async_session() as session:
            await _create_test_job(session, "detail-corr")
            await create_correction(
                session,
                job_id="detail-corr",
                field_path="part_type",
                original_value="rotational",
                corrected_value="plate",
            )
            await session.commit()

        resp = await client.get("/api/jobs/detail-corr")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["corrections"]) == 1
        assert data["corrections"][0]["field_path"] == "part_type"

    async def test_detail_falls_back_to_json_corrections(
        self, client: AsyncClient,
    ) -> None:
        """When DB has no corrections, fall back to JSON file if it exists."""
        import json
        from backend.core.correction_tracker import CORRECTIONS_DIR
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "detail-json-fb")

        # Create a JSON corrections file (simulating pre-migration data)
        CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        corr_file = CORRECTIONS_DIR / "detail-json-fb.json"
        corr_file.write_text(json.dumps([
            {"job_id": "detail-json-fb", "field_path": "d", "original_value": "50", "corrected_value": "55"},
        ]))

        try:
            resp = await client.get("/api/jobs/detail-json-fb")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["corrections"]) == 1
            assert data["corrections"][0]["field_path"] == "d"
        finally:
            corr_file.unlink(missing_ok=True)

    async def test_detail_json_fallback_handles_corrupt_file(
        self, client: AsyncClient,
    ) -> None:
        """Corrupt JSON corrections file should not crash the detail endpoint."""
        from backend.core.correction_tracker import CORRECTIONS_DIR
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "detail-corrupt")

        CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
        corr_file = CORRECTIONS_DIR / "detail-corrupt.json"
        corr_file.write_text("{broken json!!!")

        try:
            resp = await client.get("/api/jobs/detail-corrupt")
            assert resp.status_code == 200
            data = resp.json()
            # Should return empty corrections, not crash
            assert data["corrections"] == []
        finally:
            corr_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------

class TestRegenerate:
    async def test_regenerate_not_found(self, client: AsyncClient) -> None:
        resp = await client.post("/api/jobs/nonexistent/regenerate")
        assert resp.status_code == 404

    async def test_regenerate_clones_job(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(
                session, "regen-orig", input_type="text", input_text="支架",
            )

        resp = await client.post("/api/jobs/regen-orig/regenerate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cloned_from"] == "regen-orig"
        assert data["status"] == "created"
        assert data["job_id"] != "regen-orig"

        # Verify new job exists
        resp2 = await client.get(f"/api/jobs/{data['job_id']}")
        assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    async def test_delete_not_found(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/jobs/nonexistent")
        assert resp.status_code == 404

    async def test_delete_marks_as_deleted(self, client: AsyncClient) -> None:
        from backend.db.database import async_session

        async with async_session() as session:
            await _create_test_job(session, "to-delete")

        resp = await client.delete("/api/jobs/to-delete")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == "true"

        # Verify job status changed
        resp2 = await client.get("/api/jobs/to-delete")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "failed"
        assert resp2.json()["error"] == "deleted"

    async def test_delete_preserves_corrections(self, client: AsyncClient) -> None:
        """Deleting a job should keep corrections accessible via detail endpoint."""
        from backend.db.database import async_session
        from backend.db.repository import create_correction

        async with async_session() as session:
            await _create_test_job(session, "del-with-corr")
            await create_correction(
                session,
                job_id="del-with-corr",
                field_path="part_type",
                original_value="rotational",
                corrected_value="plate",
            )
            await session.commit()

        # Delete the job
        resp = await client.delete("/api/jobs/del-with-corr")
        assert resp.status_code == 200

        # Corrections should still be visible in detail
        resp2 = await client.get("/api/jobs/del-with-corr")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["status"] == "failed"
        assert data["error"] == "deleted"
        assert len(data["corrections"]) == 1
        assert data["corrections"][0]["field_path"] == "part_type"
