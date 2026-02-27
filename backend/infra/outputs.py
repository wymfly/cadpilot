"""Output file management for generated CAD models."""

from __future__ import annotations

from pathlib import Path

OUTPUTS_DIR: Path = Path("outputs").resolve()


def ensure_job_dir(job_id: str) -> Path:
    """Create and return the output directory for a specific job.

    The directory is created at ``OUTPUTS_DIR / job_id``.  The call is
    idempotent -- calling it multiple times with the same *job_id* is safe.
    """
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def get_model_url(job_id: str, fmt: str = "glb") -> str:
    """Return the URL path for a generated model file.

    Example: ``/outputs/abc123/model.glb``
    """
    return f"/outputs/{job_id}/model.{fmt}"


def get_step_path(job_id: str) -> Path:
    """Return the filesystem path where the STEP file should be stored."""
    return OUTPUTS_DIR / job_id / "model.step"
