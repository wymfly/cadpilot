"""Analysis nodes: intent parsing and vision spec."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.state import CadJobState
from backend.models.job import update_job as _update_job

from backend.core.cost_optimizer import CostOptimizer

logger = logging.getLogger(__name__)

# Module-level cost optimizer instance (result cache + model degradation)
_cost_optimizer = CostOptimizer()


async def _safe_update_job(job_id: str, **kwargs: Any) -> None:
    """Update DB job, tolerating missing records (e.g. in unit tests)."""
    try:
        await _update_job(job_id, **kwargs)
    except Exception as exc:
        logger.debug("DB update skipped for job %s: %s", job_id, exc)

LLM_TIMEOUT_S = 60.0


# Import _safe_dispatch from lifecycle (reuse pattern)
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.registry import register_node


async def _parse_intent(text: str) -> dict:
    """Async intent parsing — delegates to existing IntentParser.

    Returns a plain dict (JSON-serializable) for storage in SQLAlchemy JSON columns.
    """
    from backend.core.intent_parser import IntentParser
    from backend.infra.llm_config_manager import get_model_for_role

    llm = get_model_for_role("intent_parser").create_chat_model()

    async def _llm_callable(prompt: str, schema: type) -> Any:
        structured = llm.with_structured_output(schema)
        return await structured.ainvoke(prompt)

    parser = IntentParser(llm_callable=_llm_callable)
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


@register_node(name="analyze_intent", display_name="分析用户意图",
    requires=["job_info"], produces=["intent_spec"], input_types=["text"])
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
        return {
            "error": str(exc), "failure_reason": reason, "status": "failed",
            "_reasoning": {"error": str(exc)},
        }

    # Template matching via part_type semantic routing (replaces keyword _match_template)
    matched_template = None
    template_params: list[dict] = []
    part_type = None
    candidates: list = []
    try:
        from backend.core.template_engine import TemplateEngine
        from backend.core.spec_compiler import rank_templates

        _templates_dir = Path(__file__).parent.parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)

        if isinstance(intent, dict):
            part_type = intent.get("part_type")
        if part_type:
            candidates = engine.find_matches(part_type)
        else:
            # No part_type: skip template matching to avoid selecting wrong type
            candidates = []

        known = intent.get("known_params", {}) if isinstance(intent, dict) else {}
        ranked = rank_templates(candidates, known)

        if ranked:
            tpl = ranked[0]
            matched_template = tpl.name
            template_params = []
            for p in tpl.params:
                d = p.model_dump()
                if p.name in known:
                    d["default"] = known[p.name]
                elif p.display_name and p.display_name in known:
                    d["default"] = known[p.display_name]
                template_params.append(d)
    except Exception as exc:
        logger.debug("Template matching skipped: %s", exc)

    # Engineering standards recommendations (best-effort)
    recommendations: list[dict] = []
    try:
        from backend.core.engineering_standards import EngineeringStandards

        part_type_for_rec = None
        if isinstance(intent, dict):
            part_type_for_rec = intent.get("part_type")
        if part_type_for_rec:
            known_for_rec = intent.get("known_params", {}) if isinstance(intent, dict) else {}
            standards = EngineeringStandards()
            recs = standards.recommend_params(part_type_for_rec, known_for_rec)
            recommendations = [r.model_dump() for r in recs]
    except Exception as exc:
        logger.debug("Engineering standards recommendations skipped: %s", exc)

    await _safe_update_job(state["job_id"], status="awaiting_confirmation", intent=intent)
    # Business event: carries params + template_name for frontend ParamForm
    await _safe_dispatch("job.intent_analyzed", {
        "job_id": state["job_id"],
        "status": "intent_parsed",
        "params": template_params,
        "template_name": matched_template,
        "message": f"意图解析完成: {part_type or '未知类型'}",
    })
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"], "status": "awaiting_confirmation"})

    return {
        "intent": intent,
        "matched_template": matched_template,
        "recommendations": recommendations,
        "status": "awaiting_confirmation",
        "_reasoning": {
            "part_type": str(part_type) if part_type else "未识别",
            "template_match": f"匹配模板: {matched_template}" if matched_template else "无匹配模板",
            "candidate_count": f"{len(candidates)} 候选模板",
            "recommendations": f"{len(recommendations)} 条工程标准建议",
        },
    }


@register_node(name="analyze_vision", display_name="图纸分析",
    requires=["job_info"], produces=["drawing_spec"], input_types=["drawing"])
async def analyze_vision_node(state: CadJobState) -> dict[str, Any]:
    """Run VL model to extract DrawingSpec from uploaded image (with timeout)."""
    image_path = state.get("image_path")
    if not image_path:
        await _safe_update_job(state["job_id"], status="failed")
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": "No image_path provided", "failure_reason": "generation_error", "status": "failed"},
        )
        return {
            "error": "No image_path provided", "failure_reason": "generation_error", "status": "failed",
            "_reasoning": {"error": "No image_path provided"},
        }

    # Check result cache (keyed by image content SHA256)
    try:
        image_data = await asyncio.to_thread(Path(image_path).read_bytes)
        cached = _cost_optimizer.get_cached_result(image_data)
    except Exception:
        image_data = None
        cached = None

    if cached is not None:
        spec_dict, reasoning = cached
        logger.info("Vision analysis cache hit for job %s", state["job_id"])
    else:
        try:
            spec_dict, reasoning = await asyncio.wait_for(
                asyncio.to_thread(_run_analyze_vision, image_path),
                timeout=LLM_TIMEOUT_S,
            )
            # Store in cache for future identical images
            if image_data is not None:
                _cost_optimizer.cache_result(image_data, (spec_dict, reasoning))
        except Exception as exc:
            reason = map_exception_to_failure_reason(exc)
            logger.error("Vision analysis failed: %s (%s)", exc, reason)
            await _safe_update_job(state["job_id"], status="failed", error=str(exc))
            await _safe_dispatch(
                "job.failed",
                {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
            )
            return {
                "error": str(exc), "failure_reason": reason, "status": "failed",
                "_reasoning": {"error": str(exc)},
            }

    await _safe_dispatch(
        "job.spec_ready",
        {"job_id": state["job_id"], "drawing_spec": spec_dict, "reasoning": reasoning, "status": "drawing_spec_ready"},
    )
    await _safe_update_job(state["job_id"], status="awaiting_drawing_confirmation", drawing_spec=spec_dict)
    await _safe_dispatch("job.awaiting_confirmation", {"job_id": state["job_id"], "status": "awaiting_drawing_confirmation"})

    return {
        "drawing_spec": spec_dict,
        "status": "awaiting_drawing_confirmation",
        "_reasoning": {
            "spec_source": "VL 模型分析",
            "part_type": spec_dict.get("part_type", "unknown") if isinstance(spec_dict, dict) else "unknown",
        },
    }


