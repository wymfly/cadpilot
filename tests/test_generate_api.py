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

    def test_drawing_completed_includes_printability(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Completed event from drawing mode should include printability field."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", self._mock_pipeline_success)
        monkeypatch.setattr(gen_mod, "_convert_step_to_glb", self._mock_convert_noop)
        monkeypatch.setattr(
            gen_mod,
            "_run_printability_check",
            lambda _: {
                "printable": True,
                "profile": "fdm_standard",
                "issues": [],
                "material_estimate": {
                    "filament_weight_g": 12.5,
                    "filament_length_m": 4.2,
                    "cost_estimate_cny": 1.0,
                },
                "time_estimate": {
                    "total_minutes": 45.0,
                    "layer_count": 100,
                },
            },
        )

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert "printability" in completed[0]
        assert completed[0]["printability"]["printable"] is True
        assert "material_estimate" in completed[0]["printability"]
        assert "time_estimate" in completed[0]["printability"]

    def test_printability_failure_returns_null(
        self, client: TestClient, monkeypatch,
    ) -> None:
        """Printability check failure should not block generation — returns None."""
        import backend.api.generate as gen_mod

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", self._mock_pipeline_success)
        monkeypatch.setattr(gen_mod, "_convert_step_to_glb", self._mock_convert_noop)
        monkeypatch.setattr(gen_mod, "_run_printability_check", lambda _: None)

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fakepng", "image/png")},
        )
        events = parse_sse_events(resp.text)
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert completed[0].get("printability") is None


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
    """Integration tests: drawing upload → mocked pipeline → full SSE flow."""

    def test_full_drawing_flow_with_progress(
        self, client: TestClient, monkeypatch
    ) -> None:
        """End-to-end: upload → pipeline with progress callbacks → model_url in completed."""
        import backend.api.generate as gen_mod

        def mock_pipeline(
            image_filepath,
            output_filepath,
            config=None,
            on_spec_ready=None,
            on_progress=None,
        ):
            Path(output_filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(output_filepath).write_text("mock step content")
            if on_spec_ready:
                on_spec_ready(
                    {"part_type": "plate", "overall_dimensions": {"width": 200}},
                    "detected plate",
                )
            if on_progress:
                on_progress(
                    "geometry",
                    {"is_valid": True, "volume": 500.0, "bbox": [200, 100, 10]},
                )
                on_progress(
                    "refinement_round",
                    {"round": 1, "total": 3, "status": "refined"},
                )
                on_progress(
                    "refinement_round",
                    {"round": 2, "total": 3, "status": "PASS"},
                )

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", mock_pipeline)
        monkeypatch.setattr(
            gen_mod,
            "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("mock glb"),
        )

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("drawing.png", b"\x89PNG\r\n", "image/png")},
            data={"pipeline_config": '{"preset": "fast"}'},
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)

        # Check event flow
        statuses = [e.get("status") for e in events]
        assert "created" in statuses
        assert "completed" in statuses

        # Completed event should have model_url
        completed = [e for e in events if e.get("status") == "completed"]
        assert len(completed) == 1
        assert completed[0].get("model_url") is not None
        assert ".glb" in completed[0]["model_url"]

    def test_drawing_with_fast_preset(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Verify pipeline_config preset is parsed and passed."""
        import backend.api.generate as gen_mod

        received_config = {}

        def mock_pipeline(image_filepath, output_filepath, config=None, **kwargs):
            nonlocal received_config
            received_config = config
            Path(output_filepath).parent.mkdir(parents=True, exist_ok=True)
            Path(output_filepath).write_text("mock")

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", mock_pipeline)
        monkeypatch.setattr(
            gen_mod,
            "_convert_step_to_glb",
            lambda s, g: Path(g).write_text("mock"),
        )

        resp = client.post(
            "/api/generate/drawing",
            files={"image": ("test.png", b"fake", "image/png")},
            data={"pipeline_config": '{"preset": "fast"}'},
        )
        assert resp.status_code == 200
        # Config should have been parsed
        assert received_config is not None

    def test_drawing_pipeline_timeout_returns_failed(
        self, client: TestClient, monkeypatch
    ) -> None:
        """Pipeline timeout should return failed event."""
        import backend.api.generate as gen_mod

        def mock_timeout(*args, **kwargs):
            raise TimeoutError("Pipeline execution timed out after 300s")

        monkeypatch.setattr(gen_mod, "_run_v2_pipeline", mock_timeout)

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
