"""Tests for generate API with Job session protocol (Phase 4 Task 4.6).

Tests:
- Job model lifecycle
- POST /generate (text mode) → SSE events
- POST /generate/drawing (drawing mode) → SSE events
- POST /generate/{job_id}/confirm → SSE resume
- GET /generate/{job_id} → job status
- GET /generate/jobs → list jobs
- Error cases (404, 409, 400)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.models.job import (
    Job,
    JobStatus,
    clear_jobs,
    create_job,
    delete_job,
    get_job,
    list_jobs,
    update_job,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Clear job store before each test."""
    clear_jobs()
    yield
    clear_jobs()


@pytest.fixture()
def client():
    from backend.main import app
    return TestClient(app)


# ===================================================================
# Job model unit tests
# ===================================================================


class TestJobModel:
    def test_create_job(self) -> None:
        job = create_job("j1", input_type="text", input_text="做一个法兰")
        assert job.job_id == "j1"
        assert job.status == JobStatus.CREATED
        assert job.input_type == "text"
        assert job.input_text == "做一个法兰"

    def test_get_job(self) -> None:
        create_job("j2")
        job = get_job("j2")
        assert job is not None
        assert job.job_id == "j2"

    def test_get_nonexistent(self) -> None:
        assert get_job("nonexistent") is None

    def test_update_job(self) -> None:
        create_job("j3")
        update_job("j3", status=JobStatus.GENERATING)
        job = get_job("j3")
        assert job is not None
        assert job.status == JobStatus.GENERATING

    def test_update_nonexistent_raises(self) -> None:
        with pytest.raises(KeyError):
            update_job("nonexistent", status=JobStatus.COMPLETED)

    def test_delete_job(self) -> None:
        create_job("j4")
        delete_job("j4")
        assert get_job("j4") is None

    def test_list_jobs(self) -> None:
        create_job("a")
        create_job("b")
        jobs = list_jobs()
        assert len(jobs) == 2

    def test_clear_jobs(self) -> None:
        create_job("x")
        create_job("y")
        clear_jobs()
        assert list_jobs() == []

    def test_job_status_enum(self) -> None:
        assert JobStatus.CREATED.value == "created"
        assert JobStatus.AWAITING_CONFIRMATION.value == "awaiting_confirmation"
        assert JobStatus.COMPLETED.value == "completed"

    def test_job_serialization(self) -> None:
        job = create_job("s1", input_type="text", input_text="test")
        data = job.model_dump()
        assert data["job_id"] == "s1"
        assert data["status"] == "created"
        restored = Job.model_validate(data)
        assert restored.job_id == "s1"

    def test_job_status_transitions(self) -> None:
        create_job("t1")
        for status in [
            JobStatus.INTENT_PARSED,
            JobStatus.AWAITING_CONFIRMATION,
            JobStatus.GENERATING,
            JobStatus.REFINING,
            JobStatus.COMPLETED,
        ]:
            update_job("t1", status=status)
            assert get_job("t1").status == status


# ===================================================================
# SSE event parsing helpers
# ===================================================================


def parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE text into list of event dicts."""
    events = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if data_str:
                try:
                    events.append(json.loads(data_str))
                except json.JSONDecodeError:
                    pass
    return events


# ===================================================================
# POST /generate — text mode
# ===================================================================


class TestGenerateTextMode:
    def test_text_mode_returns_sse(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_text_mode_creates_job(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘"},
        )
        events = parse_sse_events(resp.text)
        assert len(events) >= 1
        job_id = events[0]["job_id"]
        assert job_id is not None

    def test_text_mode_event_flow(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘"},
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "intent_parsed" in statuses
        assert "awaiting_confirmation" in statuses

    def test_text_mode_job_status_persists(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘"},
        )
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        status_resp = client.get(f"/api/generate/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["status"] == "awaiting_confirmation"


# ===================================================================
# POST /generate/drawing — drawing mode
# ===================================================================


class TestGenerateDrawingMode:
    @staticmethod
    def _mock_pipeline_success(
        image_filepath, output_filepath, config=None,
        on_spec_ready=None, on_progress=None,
    ):
        """Mock pipeline that writes a fake STEP file."""
        Path(output_filepath).write_text("fake step")
        if on_spec_ready:
            on_spec_ready({"part_type": "rotational"}, "test reasoning")
        if on_progress:
            on_progress("geometry", {"is_valid": True, "volume": 100})

    @staticmethod
    def _mock_convert_noop(step_path, glb_path):
        """Mock converter that writes a fake GLB."""
        Path(glb_path).write_text("fake glb")

    def test_drawing_mode_returns_sse(
        self, client: TestClient, monkeypatch,
    ) -> None:
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", self._mock_pipeline_success)
        monkeypatch.setattr(gen_mod, "_convert_step_to_glb", self._mock_convert_noop)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_drawing_mode_event_flow(
        self, client: TestClient, monkeypatch,
    ) -> None:
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", self._mock_pipeline_success)
        monkeypatch.setattr(gen_mod, "_convert_step_to_glb", self._mock_convert_noop)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "completed" in statuses

    def test_drawing_mode_with_pipeline_returns_model_url(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When V2 pipeline succeeds, completed event should contain model_url."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", self._mock_pipeline_success)
        monkeypatch.setattr(gen_mod, "_convert_step_to_glb", self._mock_convert_noop)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert completed[0].get("model_url") is not None

    def test_drawing_pipeline_failure(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When pipeline fails, should get failed event."""
        import backend.api.generate as gen_mod

        def mock_fail(*args, **kwargs):
            raise RuntimeError("LLM timeout")

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", mock_fail)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1


# ===================================================================
# POST /generate/{job_id}/confirm
# ===================================================================


class TestConfirmParams:
    def _create_awaiting_job(self, client: TestClient) -> str:
        """Helper: create a text-mode job in AWAITING_CONFIRMATION state."""
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘"},
        )
        events = parse_sse_events(resp.text)
        return events[0]["job_id"]

    def test_confirm_returns_sse(self, client: TestClient) -> None:
        job_id = self._create_awaiting_job(client)
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {"outer_diameter": 100}},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_confirm_event_flow(self, client: TestClient) -> None:
        job_id = self._create_awaiting_job(client)
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={
                "confirmed_params": {"outer_diameter": 100, "thickness": 16},
            },
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "generating" in statuses
        assert "refining" in statuses
        assert "completed" in statuses

    def test_confirm_completes_job(self, client: TestClient) -> None:
        job_id = self._create_awaiting_job(client)
        client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {"outer_diameter": 100}},
        )
        status_resp = client.get(f"/api/generate/{job_id}")
        assert status_resp.json()["status"] == "completed"

    def test_confirm_nonexistent_job(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate/nonexistent/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 404

    def test_confirm_wrong_state(self, client: TestClient) -> None:
        job_id = self._create_awaiting_job(client)
        # First confirm succeeds
        client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {}},
        )
        # Second confirm should fail (job is now completed)
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 409

    def test_confirm_empty_params(self, client: TestClient) -> None:
        job_id = self._create_awaiting_job(client)
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {}},
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        assert any(e.get("status") == "completed" for e in events)


# ===================================================================
# GET /generate/{job_id}
# ===================================================================


class TestGetJobStatus:
    def test_get_existing_job(self, client: TestClient) -> None:
        resp = client.post(
            "/api/generate",
            json={"text": "test"},
        )
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        status_resp = client.get(f"/api/generate/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["job_id"] == job_id
        assert "status" in data

    def test_get_nonexistent_job(self, client: TestClient) -> None:
        resp = client.get("/api/generate/nonexistent")
        assert resp.status_code == 404


# ===================================================================
# GET /generate/jobs — list jobs
# ===================================================================


class TestListJobs:
    def test_list_empty(self, client: TestClient) -> None:
        resp = client.get("/api/generate/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_after_create(self, client: TestClient) -> None:
        client.post("/api/generate", json={"text": "test1"})
        client.post("/api/generate", json={"text": "test2"})
        resp = client.get("/api/generate/jobs")
        assert resp.status_code == 200
        jobs = resp.json()
        assert len(jobs) == 2


# ===================================================================
# Error cases
# ===================================================================


class TestErrorCases:
    def test_no_body(self, client: TestClient) -> None:
        resp = client.post("/api/generate")
        # Should return 422 (missing required field)
        assert resp.status_code == 422

    def test_full_lifecycle(self, client: TestClient) -> None:
        """End-to-end: create → confirm → check status."""
        # Create
        resp = client.post(
            "/api/generate",
            json={"text": "做一个法兰盘，外径100mm"},
        )
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        # Check status: awaiting_confirmation
        status = client.get(f"/api/generate/{job_id}").json()
        assert status["status"] == "awaiting_confirmation"

        # Confirm
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={
                "confirmed_params": {"outer_diameter": 100, "thickness": 16},
            },
        )
        events = parse_sse_events(resp.text)
        assert any(e.get("status") == "completed" for e in events)

        # Check final status
        status = client.get(f"/api/generate/{job_id}").json()
        assert status["status"] == "completed"
        assert status["result"] is not None
