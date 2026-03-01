"""Generation nodes: text (template) and drawing (VL pipeline) paths."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.core.spec_compiler import CompilationError, SpecCompiler
from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs").resolve()


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
        from cadpilot.knowledge.part_types import DrawingSpec
        spec_obj = DrawingSpec(**drawing_spec)

    generate_step_from_spec(
        image_filepath=image_path,
        drawing_spec=spec_obj,
        output_filepath=step_path,
    )


async def generate_step_text_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from text intent via SpecCompiler (template-first, LLM-fallback)."""
    import time as _time

    _t0 = _time.time()
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    matched = state.get("matched_template")
    stage = "template" if matched else "llm_fallback"
    await _safe_dispatch(
        "job.generating",
        {"job_id": state["job_id"], "stage": stage, "status": "generating"},
    )

    try:
        compiler = SpecCompiler()
        result = await asyncio.to_thread(
            compiler.compile,
            matched_template=matched,
            params=state.get("confirmed_params") or {},
            output_path=step_path,
            input_text=state.get("input_text") or "",
            intent=state.get("intent"),
        )
        if result.method != stage:
            await _safe_dispatch(
                "job.generating",
                {"job_id": state["job_id"], "stage": result.method, "status": "generating"},
            )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Text generation failed: %s (%s)", exc, reason)
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    _duration = _time.time() - _t0
    token_stats = dict(state.get("token_stats") or {})
    stages = list(token_stats.get("stages", []))
    stages.append({"name": "generate_step_text", "input_tokens": 0, "output_tokens": 0, "duration_s": round(_duration, 3)})
    token_stats["stages"] = stages

    return {"step_path": result.step_path, "status": "generating", "token_stats": token_stats}


async def generate_step_drawing_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from confirmed DrawingSpec via VL pipeline."""
    import time as _time

    _t0 = _time.time()
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

    _duration = _time.time() - _t0
    token_stats = dict(state.get("token_stats") or {})
    stages = list(token_stats.get("stages", []))
    stages.append({"name": "generate_step_drawing", "input_tokens": 0, "output_tokens": 0, "duration_s": round(_duration, 3)})
    token_stats["stages"] = stages

    return {"step_path": step_path, "status": "generating", "token_stats": token_stats}
