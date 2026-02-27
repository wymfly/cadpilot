"""Tests for backend.infra.outputs module."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.infra import outputs


@pytest.fixture(autouse=True)
def _override_outputs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect OUTPUTS_DIR to a temporary directory for every test."""
    monkeypatch.setattr(outputs, "OUTPUTS_DIR", tmp_path)


class TestEnsureJobDir:
    """Tests for ensure_job_dir."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        job_dir = outputs.ensure_job_dir("job-001")
        assert job_dir == tmp_path / "job-001"
        assert job_dir.is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        first = outputs.ensure_job_dir("job-002")
        second = outputs.ensure_job_dir("job-002")
        assert first == second
        assert first.is_dir()


class TestGetModelUrl:
    """Tests for get_model_url."""

    def test_default_format(self) -> None:
        url = outputs.get_model_url("job-003")
        assert url == "/outputs/job-003/model.glb"

    def test_custom_format(self) -> None:
        url = outputs.get_model_url("job-004", fmt="stl")
        assert url == "/outputs/job-004/model.stl"


class TestGetStepPath:
    """Tests for get_step_path."""

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        step_path = outputs.get_step_path("job-005")
        assert step_path == tmp_path / "job-005" / "model.step"
        assert isinstance(step_path, Path)
