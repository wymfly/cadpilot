"""Analysis nodes: intent parsing, vision spec, organic stub."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

LLM_TIMEOUT_S = 60.0


# Import _safe_dispatch from lifecycle (reuse pattern)
from backend.graph.nodes.lifecycle import _safe_dispatch


async def _parse_intent(text: str) -> dict:
    """Async intent parsing — delegates to existing IntentParser."""
    from backend.core.intent_parser import IntentParser
    parser = IntentParser()
    return await parser.aparse(text)


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
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason},
        )
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    # Template matching (best-effort)
    matched_template = None
    try:
        from backend.api.generate import _match_template
        template_result = _match_template(state.get("input_text") or "")
        if template_result and template_result[0]:
            matched_template = template_result[0].name
    except Exception:
        pass

    await _safe_dispatch(
        "job.intent_analyzed",
        {"job_id": state["job_id"], "intent": intent, "matched_template": matched_template},
    )
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"]})
    return {
        "intent": intent,
        "matched_template": matched_template,
        "status": "awaiting_confirmation",
    }


async def analyze_vision_node(state: CadJobState) -> dict[str, Any]:
    """Run VL model to extract DrawingSpec from uploaded image (with timeout)."""
    await _safe_dispatch("job.vision_analyzing", {"job_id": state["job_id"]})

    try:
        spec_dict, reasoning = await asyncio.wait_for(
            asyncio.to_thread(_run_analyze_vision, state["image_path"]),
            timeout=LLM_TIMEOUT_S,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Vision analysis failed: %s (%s)", exc, reason)
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason},
        )
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    await _safe_dispatch(
        "job.spec_ready",
        {"job_id": state["job_id"], "drawing_spec": spec_dict, "reasoning": reasoning},
    )
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"]})
    return {"drawing_spec": spec_dict, "status": "awaiting_drawing_confirmation"}


async def stub_organic_node(state: CadJobState) -> dict[str, Any]:
    """Organic input: no LLM analysis needed, go straight to HITL."""
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"]})
    return {"status": "awaiting_confirmation"}
