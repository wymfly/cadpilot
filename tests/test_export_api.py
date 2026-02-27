"""Tests for export API — job_id and step_path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.main import app

    return TestClient(app)


class TestExportRequest:
    """Test the ExportRequest validation and endpoint routing."""

    def test_missing_both_fields_returns_400(self, client: TestClient) -> None:
        resp = client.post("/api/export", json={"config": {"format": "stl"}})
        assert resp.status_code == 400
        assert "Either job_id or step_path is required" in resp.json()["detail"]

    def test_nonexistent_job_id_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/export",
            json={"job_id": "nonexistent-job", "config": {"format": "stl"}},
        )
        assert resp.status_code == 404
        assert "STEP file not found" in resp.json()["detail"]

    def test_step_path_outside_allowed_dir_returns_403(
        self, client: TestClient,
    ) -> None:
        resp = client.post(
            "/api/export",
            json={"step_path": "/etc/passwd", "config": {"format": "stl"}},
        )
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]

    def test_step_format_returns_raw_file(
        self, client: TestClient, tmp_path: Path, monkeypatch,
    ) -> None:
        """When format=step, the raw STEP file should be returned."""
        import backend.api.export as export_mod

        # Create a fake STEP file inside the allowed directory
        fake_outputs = tmp_path / "outputs"
        fake_outputs.mkdir()
        step_file = fake_outputs / "test.step"
        step_file.write_text("STEP;fake")

        # Patch _ALLOWED_DIR to tmp_path
        monkeypatch.setattr(export_mod, "_ALLOWED_DIR", fake_outputs)

        resp = client.post(
            "/api/export",
            json={
                "step_path": str(step_file),
                "config": {"format": "step"},
            },
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/STEP")
        assert resp.content == b"STEP;fake"

    def test_job_id_resolves_via_get_step_path(
        self, client: TestClient, tmp_path: Path, monkeypatch,
    ) -> None:
        """When job_id is provided, it should resolve through get_step_path."""
        import backend.api.export as export_mod
        import backend.infra.outputs as outputs_mod

        fake_outputs = tmp_path / "outputs"
        fake_outputs.mkdir()
        job_dir = fake_outputs / "test-job-123"
        job_dir.mkdir()
        step_file = job_dir / "model.step"
        step_file.write_text("STEP;from-job")

        monkeypatch.setattr(outputs_mod, "OUTPUTS_DIR", fake_outputs)
        monkeypatch.setattr(export_mod, "_ALLOWED_DIR", fake_outputs)

        resp = client.post(
            "/api/export",
            json={
                "job_id": "test-job-123",
                "config": {"format": "step"},
            },
        )
        assert resp.status_code == 200
        assert resp.content == b"STEP;from-job"

    def test_nonexistent_step_path_returns_404(
        self, client: TestClient, tmp_path: Path, monkeypatch,
    ) -> None:
        import backend.api.export as export_mod

        fake_outputs = tmp_path / "outputs"
        fake_outputs.mkdir()
        monkeypatch.setattr(export_mod, "_ALLOWED_DIR", fake_outputs)

        resp = client.post(
            "/api/export",
            json={
                "step_path": str(fake_outputs / "missing.step"),
                "config": {"format": "stl"},
            },
        )
        assert resp.status_code == 404
