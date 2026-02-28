"""Generation nodes: text (template) and drawing (VL pipeline) paths."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs").resolve()


def _run_template_generation(
    job_id: str,
    confirmed_params: dict,
    matched_template: str | None,
    step_path: str,
) -> str:
    """Synchronous template generation — delegates to existing logic."""
    from backend.api.generate import _run_template_generation as _orig_run
    from backend.models.job import Job

    # Build a minimal mock job object for the legacy function signature
    job = Job(
        job_id=job_id,
        input_type="text",
        input_text="",
        created_at="",
    )
    _orig_run(job, confirmed_params, step_path)
    return step_path


def _run_generate_from_spec(
    image_path: str,
    drawing_spec: dict | None,
    step_path: str,
) -> None:
    """Synchronous drawing generation — delegates to pipeline."""
    from backend.pipeline.pipeline import generate_step_from_spec

    generate_step_from_spec(
        image_filepath=image_path,
        drawing_spec=drawing_spec,
        output_filepath=step_path,
    )


async def generate_step_text_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from text intent via TemplateEngine + Sandbox."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    await _safe_dispatch(
        "job.generating",
        {"job_id": state["job_id"], "stage": "template"},
    )

    try:
        result_path = await asyncio.to_thread(
            _run_template_generation,
            state["job_id"],
            state.get("confirmed_params") or {},
            state.get("matched_template"),
            step_path,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Text generation failed: %s (%s)", exc, reason)
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    return {"step_path": result_path, "status": "generating"}


async def generate_step_drawing_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from confirmed DrawingSpec via VL pipeline."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    await _safe_dispatch(
        "job.generating",
        {"job_id": state["job_id"], "stage": "drawing_pipeline"},
    )

    try:
        await asyncio.to_thread(
            _run_generate_from_spec,
            image_path=state["image_path"],
            drawing_spec=state.get("confirmed_spec") or state.get("drawing_spec"),
            step_path=step_path,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Drawing generation failed: %s (%s)", exc, reason)
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    return {"step_path": step_path, "status": "generating"}
