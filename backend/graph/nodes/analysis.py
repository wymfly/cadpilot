"""Analysis nodes: intent parsing, vision spec, organic stub."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.state import CadJobState
from backend.models.job import update_job as _update_job

logger = logging.getLogger(__name__)


async def _safe_update_job(job_id: str, **kwargs: Any) -> None:
    """Update DB job, tolerating missing records (e.g. in unit tests)."""
    try:
        await _update_job(job_id, **kwargs)
    except (KeyError, Exception) as exc:
        logger.debug("DB update skipped for job %s: %s", job_id, exc)

LLM_TIMEOUT_S = 60.0


# Import _safe_dispatch from lifecycle (reuse pattern)
from backend.graph.nodes.lifecycle import _safe_dispatch


async def _parse_intent(text: str) -> dict:
    """Async intent parsing — delegates to existing IntentParser.

    Returns a plain dict (JSON-serializable) for storage in SQLAlchemy JSON columns.
    """
    from backend.core.intent_parser import IntentParser
    parser = IntentParser()
    result = await parser.parse(text)
    # IntentParser may return a Pydantic model; convert to dict for DB/JSON.
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


def _run_analyze_vision(image_path: str) -> tuple:
    """Synchronous vision analysis — delegates to pipeline."""
    from backend.pipeline.pipeline import analyze_vision_spec
    spec, reasoning = analyze_vision_spec(image_path)
    spec_dict = spec.model_dump() if hasattr(spec, "model_dump") else spec
    return spec_dict, reasoning


async def analyze_intent_node(state: CadJobState) -> dict[str, Any]:
    """Parse user text into IntentSpec via LLM (with timeout)."""
    try:
        intent = await asyncio.wait_for(
            _parse_intent(state.get("input_text") or ""),
            timeout=LLM_TIMEOUT_S,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Intent analysis failed: %s (%s)", exc, reason)
        await _safe_update_job(state["job_id"], status="failed", error=str(exc))
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
        )
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    # Template matching (best-effort)
    matched_template = None
    try:
        from backend.pipeline.vision_cad_pipeline import _match_template
        template_result = _match_template(state.get("input_text") or "")
        if template_result and template_result[0]:
            matched_template = template_result[0].name
    except Exception:
        pass

    await _safe_dispatch(
        "job.intent_analyzed",
        {"job_id": state["job_id"], "intent": intent, "matched_template": matched_template, "status": "intent_parsed"},
    )
    await _safe_update_job(state["job_id"], status="awaiting_confirmation", intent=intent)
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"], "status": "awaiting_confirmation"})
    return {
        "intent": intent,
        "matched_template": matched_template,
        "status": "awaiting_confirmation",
    }


async def analyze_vision_node(state: CadJobState) -> dict[str, Any]:
    """Run VL model to extract DrawingSpec from uploaded image (with timeout)."""
    await _safe_dispatch("job.vision_analyzing", {"job_id": state["job_id"], "status": "analyzing"})

    image_path = state.get("image_path")
    if not image_path:
        await _safe_update_job(state["job_id"], status="failed")
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": "No image_path provided", "failure_reason": "generation_error", "status": "failed"},
        )
        return {"error": "No image_path provided", "failure_reason": "generation_error", "status": "failed"}

    try:
        spec_dict, reasoning = await asyncio.wait_for(
            asyncio.to_thread(_run_analyze_vision, image_path),
            timeout=LLM_TIMEOUT_S,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Vision analysis failed: %s (%s)", exc, reason)
        await _safe_update_job(state["job_id"], status="failed", error=str(exc))
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
        )
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    await _safe_dispatch(
        "job.spec_ready",
        {"job_id": state["job_id"], "drawing_spec": spec_dict, "reasoning": reasoning, "status": "drawing_spec_ready"},
    )
    await _safe_update_job(state["job_id"], status="awaiting_drawing_confirmation", drawing_spec=spec_dict)
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"], "status": "awaiting_drawing_confirmation"})
    return {"drawing_spec": spec_dict, "status": "awaiting_drawing_confirmation"}


async def stub_organic_node(state: CadJobState) -> dict[str, Any]:
    """Organic input: no LLM analysis needed, go straight to HITL."""
    await _safe_update_job(state["job_id"], status="awaiting_confirmation")
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"], "status": "awaiting_confirmation"})
    return {"status": "awaiting_confirmation"}
