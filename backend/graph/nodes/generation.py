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

    # Build a minimal mock job object for the legacy function signature.
    # The legacy function reads template_name from job.result dict.
    job = Job(
        job_id=job_id,
        input_type="text",
        input_text="",
        created_at="",
    )
    job.result = {"template_name": matched_template} if matched_template else None
    success = _orig_run(job, confirmed_params, step_path)
    if not success:
        raise RuntimeError(
            f"Template generation failed: template={matched_template!r}"
        )
    return step_path


def _run_generate_from_spec(
    image_path: str,
    drawing_spec: dict | None,
    step_path: str,
) -> None:
    """Synchronous drawing generation — delegates to pipeline.

    Deserializes drawing_spec dict → DrawingSpec Pydantic model before
    calling the pipeline, which expects attribute access (spec.part_type).
    """
    from backend.pipeline.pipeline import generate_step_from_spec

    # Pipeline expects DrawingSpec model, not a plain dict.
    spec_obj = drawing_spec
    if isinstance(drawing_spec, dict):
        from cad3dify.knowledge.part_types import DrawingSpec
        spec_obj = DrawingSpec(**drawing_spec)

    generate_step_from_spec(
        image_filepath=image_path,
        drawing_spec=spec_obj,
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
        {"job_id": state["job_id"], "stage": "template", "status": "generating"},
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
        {"job_id": state["job_id"], "stage": "drawing_pipeline", "status": "generating"},
    )

    try:
        image_path = state.get("image_path")
        if not image_path:
            return {"error": "No image_path provided", "failure_reason": "generation_error", "status": "failed"}
        await asyncio.to_thread(
            _run_generate_from_spec,
            image_path=image_path,
            drawing_spec=state.get("confirmed_spec") or state.get("drawing_spec"),
            step_path=step_path,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Drawing generation failed: %s (%s)", exc, reason)
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    return {"step_path": step_path, "status": "generating"}
