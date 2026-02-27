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
            JobStatus.AWAITING_DRAWING_CONFIRMATION,
            JobStatus.GENERATING,
            JobStatus.REFINING,
            JobStatus.COMPLETED,
        ]:
            update_job("t1", status=status)
            assert get_job("t1").status == status

    def test_awaiting_drawing_confirmation_status(self) -> None:
        assert (
            JobStatus.AWAITING_DRAWING_CONFIRMATION.value
            == "awaiting_drawing_confirmation"
        )

    def test_drawing_spec_fields(self) -> None:
        job = create_job("d1", input_type="drawing")
        assert job.drawing_spec is None
        assert job.drawing_spec_confirmed is None
        assert job.image_path is None

        spec = {"part_type": "ROTATIONAL", "overall_dimensions": {"d": 50}}
        update_job(
            "d1",
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=spec,
            image_path="/uploads/drawing.png",
        )
        job = get_job("d1")
        assert job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
        assert job.drawing_spec == spec
        assert job.image_path == "/uploads/drawing.png"

        confirmed = {**spec, "overall_dimensions": {"d": 52}}
        update_job("d1", drawing_spec_confirmed=confirmed)
        job = get_job("d1")
        assert job.drawing_spec_confirmed == confirmed

    def test_drawing_job_serialization(self) -> None:
        job = create_job("d2", input_type="drawing")
        spec = {"part_type": "PLATE", "overall_dimensions": {"w": 100}}
        update_job(
            "d2",
            drawing_spec=spec,
            image_path="/tmp/img.jpg",
        )
        data = get_job("d2").model_dump()
        assert data["drawing_spec"] == spec
        assert data["image_path"] == "/tmp/img.jpg"
        restored = Job.model_validate(data)
        assert restored.drawing_spec == spec


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

    def test_text_mode_returns_params(self, client: TestClient) -> None:
        """intent_parsed event should contain params array."""
        resp = client.post("/api/generate", json={"text": "做一个法兰盘"})
        events = parse_sse_events(resp.text)
        parsed = [e for e in events if e.get("status") == "intent_parsed"]
        assert len(parsed) >= 1
        # params should be a list (might be empty if no template matched)
        assert "params" in parsed[0]
        assert isinstance(parsed[0]["params"], list)

    def test_text_mode_template_match(self, client: TestClient) -> None:
        """When text contains a known display_name, template_name should be set."""
        resp = client.post("/api/generate", json={"text": "做一个法兰盘"})
        events = parse_sse_events(resp.text)
        parsed = [e for e in events if e.get("status") == "intent_parsed"]
        assert len(parsed) >= 1
        # "法兰盘" matches the rotational_flange_disk template
        assert parsed[0].get("template_name") == "rotational_flange_disk"
        assert len(parsed[0]["params"]) > 0

    def test_text_mode_no_match(self, client: TestClient) -> None:
        """When text has no known keyword, template_name should be None."""
        resp = client.post("/api/generate", json={"text": "做一个完全未知的东西"})
        events = parse_sse_events(resp.text)
        parsed = [e for e in events if e.get("status") == "intent_parsed"]
        assert len(parsed) >= 1
        assert parsed[0].get("template_name") is None
        assert parsed[0]["params"] == []

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
    """Drawing mode now follows HITL flow: analyze → pause → (confirm in T9)."""

    _MOCK_SPEC_DATA = {
        "part_type": "rotational",
        "overall_dimensions": {"d": 50, "h": 30},
    }

    @staticmethod
    def _mock_analyze_success(image_filepath):
        """Mock analyze_drawing that returns a spec-like object."""
        from unittest.mock import MagicMock

        spec = MagicMock()
        spec.model_dump.return_value = TestGenerateDrawingMode._MOCK_SPEC_DATA
        return spec, "test reasoning"

    @staticmethod
    def _mock_analyze_none(image_filepath):
        """Mock analyze_drawing that returns None (analysis failure)."""
        return None, None

    def test_drawing_mode_returns_sse(
        self, client: TestClient, monkeypatch,
    ) -> None:
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_success)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_drawing_mode_event_flow_pauses(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Drawing route should emit drawing_spec_ready and NOT complete."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_success)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "awaiting_drawing_confirmation" in statuses
        assert "completed" not in statuses  # Should NOT complete yet!

    def test_drawing_spec_ready_contains_spec(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """drawing_spec_ready event should contain the DrawingSpec data."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_success)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        spec_events = [
            e for e in events
            if e.get("status") == "awaiting_drawing_confirmation"
        ]
        assert len(spec_events) == 1
        assert "drawing_spec" in spec_events[0]
        assert spec_events[0]["drawing_spec"]["part_type"] == "rotational"
        assert spec_events[0]["reasoning"] == "test reasoning"

    def test_drawing_spec_stored_in_job(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Job should have drawing_spec and image_path after analysis."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_success)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        job = get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
        assert job.drawing_spec == self._MOCK_SPEC_DATA
        assert job.image_path is not None

    def test_drawing_analysis_returns_none(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When analysis returns None spec, should get failed event."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_none)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1

    def test_drawing_analysis_exception(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """When analysis raises an exception, should get failed event."""
        import backend.api.generate as gen_mod

        def mock_fail(image_filepath):
            raise RuntimeError("VL model timeout")

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", mock_fail)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1
        assert "timeout" in failed[0].get("message", "").lower()

    def test_drawing_job_status_persists(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Job status should be queryable via GET after drawing analysis."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze_success)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        status_resp = client.get(f"/api/generate/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["status"] == "awaiting_drawing_confirmation"
        assert data["drawing_spec"] is not None


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

    def test_confirm_with_template(self, client: TestClient, monkeypatch) -> None:
        """When template matches and executes, completed should have model_url."""
        import backend.api.generate as gen_mod

        # Mock _run_template_generation to succeed and create a fake STEP file
        def _mock_run(job, params, step_path):
            Path(step_path).parent.mkdir(parents=True, exist_ok=True)
            Path(step_path).write_text("fake step")
            return True

        monkeypatch.setattr(gen_mod, "_run_template_generation", _mock_run)
        monkeypatch.setattr(
            gen_mod, "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("fake glb"),
        )

        job_id = self._create_awaiting_job(client)
        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {"outer_diameter": 100}},
        )
        events = parse_sse_events(resp.text)
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert completed[0].get("model_url") is not None

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


# ===================================================================
# Integration tests — drawing mode full flow
# ===================================================================


class TestDrawingModeIntegration:
    """Integration tests: drawing upload → HITL analysis → pause."""

    @staticmethod
    def _mock_analyze(image_filepath):
        """Mock that returns a spec-like object with model_dump."""
        from unittest.mock import MagicMock

        spec = MagicMock()
        spec.model_dump.return_value = {
            "part_type": "plate",
            "overall_dimensions": {"width": 200, "height": 100, "thickness": 10},
        }
        return spec, "detected plate from drawing"

    def test_drawing_hitl_flow(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Drawing upload → analyze → drawing_spec_ready → job paused."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", self._mock_analyze)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("drawing.png", b"\x89PNG\r\n", "image/png")},
            data={"pipeline_config": '{"preset": "fast"}'},
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        # Check event flow: created → analyzing → drawing_spec_ready
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "analyzing" in statuses
        assert "awaiting_drawing_confirmation" in statuses
        assert "completed" not in statuses

        # drawing_spec_ready event has spec data
        spec_events = [
            e for e in events
            if e.get("status") == "awaiting_drawing_confirmation"
        ]
        assert len(spec_events) == 1
        assert spec_events[0]["drawing_spec"]["part_type"] == "plate"
        assert spec_events[0]["reasoning"] == "detected plate from drawing"

        # Job is paused
        job_id = events[0]["job_id"]
        job = get_job(job_id)
        assert job.status == JobStatus.AWAITING_DRAWING_CONFIRMATION
        assert job.drawing_spec is not None
        assert job.image_path is not None

    def test_drawing_analysis_timeout_returns_failed(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Analysis timeout should return failed event."""
        import backend.api.generate as gen_mod

        def mock_timeout(image_filepath):
            raise TimeoutError("VL model timed out after 300s")

        monkeypatch.setattr(gen_mod, "_run_analyze_drawing", mock_timeout)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fake", "image/png")},
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1
        assert (
            "timed out" in failed[0].get("message", "").lower()
            or "timeout" in failed[0].get("message", "").lower()
        )


# ===================================================================
# POST /generate/drawing/{job_id}/confirm — drawing confirm (T9)
# ===================================================================


class TestDrawingConfirm:
    """Tests for POST /generate/drawing/{job_id}/confirm endpoint."""

    _VALID_CONFIRMED_SPEC: dict = {
        "part_type": "rotational",
        "description": "Test rotational part",
        "base_body": {"method": "revolve"},
        "overall_dimensions": {"d": 50, "h": 30},
    }

    def _create_awaiting_drawing_job(self, job_id: str = "dc-test") -> str:
        """Helper: create a job in AWAITING_DRAWING_CONFIRMATION state."""
        create_job(job_id, input_type="drawing")
        update_job(
            job_id,
            status=JobStatus.AWAITING_DRAWING_CONFIRMATION,
            drawing_spec=self._VALID_CONFIRMED_SPEC,
            image_path="/tmp/test-drawing.png",
        )
        return job_id

    def test_drawing_confirm_resumes_generation(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Confirm should resume pipeline and reach completed status."""
        import backend.api.generate as gen_mod

        job_id = self._create_awaiting_drawing_job()

        def mock_generate(
            image_filepath, drawing_spec, output_filepath,
            on_progress=None, config=None,
        ):
            Path(output_filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(output_filepath).write_text("fake step content")

        monkeypatch.setattr(gen_mod, "_run_generate_from_spec", mock_generate)
        monkeypatch.setattr(
            gen_mod, "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("fake glb"),
        )
        monkeypatch.setattr(gen_mod, "_run_printability_check", lambda p: None)

        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "generating" in statuses
        assert "completed" in statuses

        # Job should be COMPLETED
        job = get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.result is not None
        assert "model_url" in job.result

    def test_drawing_confirm_nonexistent_job(
        self, client: TestClient,
    ) -> None:
        """Confirm on nonexistent job should return 404."""
        resp = client.post(
            "/api/generate/drawing/nonexistent-id/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 404

    def test_drawing_confirm_wrong_state(
        self, client: TestClient,
    ) -> None:
        """Confirm on job not in AWAITING_DRAWING_CONFIRMATION should return 409."""
        job_id = "dc-wrong-state"
        create_job(job_id, input_type="drawing")
        # Job is in CREATED state, not AWAITING_DRAWING_CONFIRMATION
        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 409

    def test_drawing_confirm_disclaimer_required(
        self, client: TestClient,
    ) -> None:
        """Confirm with disclaimer_accepted=False should return 400."""
        job_id = self._create_awaiting_drawing_job()
        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": False,
            },
        )
        assert resp.status_code == 400

    def test_drawing_confirm_with_printability(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Completed event should include printability data when available."""
        import backend.api.generate as gen_mod

        job_id = self._create_awaiting_drawing_job()

        def mock_generate(
            image_filepath, drawing_spec, output_filepath,
            on_progress=None, config=None,
        ):
            Path(output_filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(output_filepath).write_text("fake step")

        monkeypatch.setattr(gen_mod, "_run_generate_from_spec", mock_generate)
        monkeypatch.setattr(
            gen_mod, "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("fake glb"),
        )
        printability = {"overall_score": 85, "issues": []}
        monkeypatch.setattr(
            gen_mod, "_run_printability_check", lambda p: printability,
        )

        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        events = parse_sse_events(resp.text)
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert completed[0].get("printability") == printability

    def test_drawing_confirm_pipeline_failure(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Pipeline exception should emit failed event."""
        import backend.api.generate as gen_mod

        job_id = self._create_awaiting_drawing_job()

        def mock_fail(
            image_filepath, drawing_spec, output_filepath,
            on_progress=None, config=None,
        ):
            raise RuntimeError("CadQuery build failed")

        monkeypatch.setattr(gen_mod, "_run_generate_from_spec", mock_fail)

        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1
        assert "管道执行失败" in failed[0].get("message", "")

    def test_drawing_confirm_no_step_file(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Pipeline success but no STEP file should emit failed."""
        import backend.api.generate as gen_mod

        job_id = self._create_awaiting_drawing_job("dc-no-step")

        def mock_generate(
            image_filepath, drawing_spec, output_filepath,
            on_progress=None, config=None,
        ):
            pass  # Don't create the STEP file

        monkeypatch.setattr(gen_mod, "_run_generate_from_spec", mock_generate)

        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": self._VALID_CONFIRMED_SPEC,
                "disclaimer_accepted": True,
            },
        )
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1
        assert "STEP" in failed[0].get("message", "")

    def test_drawing_confirm_invalid_spec(
        self, client: TestClient,
    ) -> None:
        """Invalid confirmed_spec should emit failed event (not crash)."""
        job_id = self._create_awaiting_drawing_job()

        resp = client.post(
            f"/api/generate/drawing/{job_id}/confirm",
            json={
                "confirmed_spec": {"invalid": "data"},
                "disclaimer_accepted": True,
            },
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        failed = [e for e in events if e.get("status") == "failed"]
        assert len(failed) >= 1
        assert "参数解析失败" in failed[0].get("message", "")


# ===================================================================
# Integration tests — text mode full lifecycle
# ===================================================================


class TestTextModeIntegration:
    """Integration tests: text mode → template matching → confirm → generate."""

    def test_text_to_confirm_full_flow(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Full lifecycle: text input → intent_parsed with params → confirm → completed."""
        import backend.api.generate as gen_mod

        # Step 1: Text input
        resp = client.post("/api/generate", json={"text": "做一个法兰盘"})
        events = parse_sse_events(resp.text)
        job_id = events[0]["job_id"]

        # Check intent_parsed has params
        parsed = [e for e in events if e.get("status") == "intent_parsed"]
        assert len(parsed) >= 1
        assert "params" in parsed[0]

        # Step 2: Confirm params (mock the generation)
        def _mock_run(job, params, step_path):
            Path(step_path).parent.mkdir(parents=True, exist_ok=True)
            Path(step_path).write_text("fake step")
            return True

        monkeypatch.setattr(gen_mod, "_run_template_generation", _mock_run)
        monkeypatch.setattr(
            gen_mod,
            "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("fake glb"),
        )

        resp = client.post(
            f"/api/generate/{job_id}/confirm",
            json={"confirmed_params": {"outer_diameter": 100, "thickness": 16}},
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "generating" in statuses
        assert "completed" in statuses

        # Step 3: Verify final job status
        status_resp = client.get(f"/api/generate/{job_id}")
        assert status_resp.json()["status"] == "completed"

    def test_text_mode_no_match_still_works(self, client: TestClient) -> None:
        """When no template matches, should still complete the flow gracefully."""
        resp = client.post(
            "/api/generate", json={"text": "一个完全未知的东西xyz"}
        )
        events = parse_sse_events(resp.text)
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "intent_parsed" in statuses
        assert "awaiting_confirmation" in statuses

        # params should be empty list
        parsed = [e for e in events if e.get("status") == "intent_parsed"]
        assert parsed[0].get("params") == []
        assert parsed[0].get("template_name") is None
