"""Generation nodes: text (template) and drawing (VL pipeline) paths."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.core.spec_compiler import CompilationError, SpecCompiler
from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.registry import register_node
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs").resolve()


def _run_generate_from_spec(
    image_path: str,
    drawing_spec: dict | None,
    step_path: str,
) -> str | None:
    """Synchronous drawing generation — delegates to pipeline.

    Deserializes drawing_spec dict → DrawingSpec Pydantic model before
    calling the pipeline, which expects attribute access (spec.part_type).

    Returns the generated CadQuery code string, or None on failure.
    """
    from backend.pipeline.pipeline import generate_step_from_spec

    # Pipeline expects DrawingSpec model, not a plain dict.
    spec_obj = drawing_spec
    if isinstance(drawing_spec, dict):
        from cadpilot.knowledge.part_types import DrawingSpec
        spec_obj = DrawingSpec(**drawing_spec)

    return generate_step_from_spec(
        image_filepath=image_path,
        drawing_spec=spec_obj,
        output_filepath=step_path,
    )


@register_node(name="generate_step_text", display_name="文本→STEP生成",
    requires=["confirmed_params"], produces=["step_model"], input_types=["text"])
async def generate_step_text_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from text intent via SpecCompiler (template-first, LLM-fallback)."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {"_reasoning": {"skip": "idempotent, STEP already exists"}}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    matched = state.get("matched_template")

    # Business event: frontend shows "Generating..." phase
    await _safe_dispatch("job.generating", {
        "job_id": state["job_id"], "status": "generating",
        "message": f"正在生成 STEP 模型（模板: {matched or 'LLM'}）",
    })

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
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Text generation failed: %s (%s)", exc, reason)
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
        )
        return {
            "error": str(exc), "failure_reason": reason, "status": "failed",
            "_reasoning": {"error": str(exc)},
        }

    # Persist generated code to file
    code_text = result.cadquery_code or ""
    if code_text:
        code_path = job_dir / "code.py"
        code_path.write_text(code_text, encoding="utf-8")

    return {
        "step_path": result.step_path,
        "generated_code": code_text or None,
        "status": "generating",
        "_reasoning": {
            "method": result.method,
            "template": result.template_name or "N/A",
            "step_path": result.step_path,
        },
    }


@register_node(name="generate_step_drawing", display_name="图纸→STEP生成",
    requires=["confirmed_params"], produces=["step_model"], input_types=["drawing"])
async def generate_step_drawing_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from confirmed DrawingSpec via VL pipeline."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {"_reasoning": {"skip": "idempotent, STEP already exists"}}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    image_path = state.get("image_path")

    # Business event: frontend shows "Generating..." phase
    await _safe_dispatch("job.generating", {
        "job_id": state["job_id"], "status": "generating",
        "message": "正在通过 V2 管道生成 STEP 模型",
    })

    code_text: str | None = None
    try:
        if not image_path:
            return {
                "error": "No image_path provided", "failure_reason": "generation_error", "status": "failed",
                "_reasoning": {"error": "No image_path provided"},
            }
        raw_code = await asyncio.to_thread(
            _run_generate_from_spec,
            image_path=image_path,
            drawing_spec=state.get("confirmed_spec") or state.get("drawing_spec"),
            step_path=step_path,
        )
        if isinstance(raw_code, str):
            code_text = raw_code
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Drawing generation failed: %s (%s)", exc, reason)
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
        )
        return {
            "error": str(exc), "failure_reason": reason, "status": "failed",
            "_reasoning": {"error": str(exc)},
        }

    # Persist generated code to file
    if code_text:
        code_path = job_dir / "code.py"
        code_path.write_text(code_text, encoding="utf-8")

    return {
        "step_path": step_path,
        "generated_code": code_text,
        "status": "generating",
        "_reasoning": {
            "pipeline": "V2 drawing pipeline",
            "image_path": image_path or "N/A",
        },
    }
