"""Lifecycle nodes: create_job, confirm_with_user, finalize."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import adispatch_custom_event

from backend.graph.state import CadJobState, STATE_TO_ORM_MAPPING
from backend.models.job import create_job, update_job

logger = logging.getLogger(__name__)


async def _safe_dispatch(event_name: str, payload: dict[str, Any]) -> None:
    """Dispatch a custom event, tolerating missing run context or stubs.

    When called outside a LangGraph execution context (e.g. in unit tests),
    ``adispatch_custom_event`` raises ``RuntimeError`` because there is no
    parent run id.  We silently swallow that so node functions remain testable
    in isolation.
    """
    try:
        await adispatch_custom_event(event_name, payload)
    except RuntimeError:
        # No parent run context — expected in unit tests
        pass


async def create_job_node(state: CadJobState) -> dict[str, Any]:
    """Create DB Job record and dispatch job.created event."""
    await create_job(
        job_id=state["job_id"],
        input_type=state["input_type"],
        input_text=state.get("input_text") or "",
    )
    if state.get("image_path"):
        await update_job(state["job_id"], image_path=state["image_path"])
    await _safe_dispatch(
        "job.created",
        {"job_id": state["job_id"], "input_type": state["input_type"], "status": "created"},
    )

    # Initialize token tracker (serialized as dict in state)
    from backend.infra.token_tracker import TokenTracker

    tracker = TokenTracker()
    return {"status": "created", "token_stats": tracker.get_stats()}


async def confirm_with_user_node(state: CadJobState) -> dict[str, Any]:
    """Process Command(resume=...) data after interrupt.

    By the time this node executes, LangGraph has already merged the
    resume payload into state (confirmed_params / confirmed_spec / disclaimer_accepted).
    We just advance the status.
    """
    return {"status": "confirmed"}


async def finalize_node(state: CadJobState) -> dict[str, Any]:
    """Write final state to DB and dispatch terminal event."""
    is_failed = state.get("error") is not None or state.get("status") == "failed"
    final_status = "failed" if is_failed else "completed"

    # Build ORM update kwargs using STATE_TO_ORM_MAPPING
    orm_kwargs: dict[str, Any] = {"status": final_status}
    direct_fields = ["intent", "drawing_spec", "error"]
    for field in direct_fields:
        val = state.get(field)
        if val is not None:
            orm_kwargs[field] = val

    for state_key, orm_col in STATE_TO_ORM_MAPPING.items():
        val = state.get(state_key)
        if val is not None:
            orm_kwargs[orm_col] = val

    # Assemble `result` JSON from step_path + model_url
    result_dict: dict[str, Any] = {}
    if state.get("step_path"):
        result_dict["step_path"] = state["step_path"]
    if state.get("model_url"):
        result_dict["model_url"] = state["model_url"]
    if state.get("matched_template"):
        result_dict["template_name"] = state["matched_template"]
    # Organic input: merge mesh/printability results
    input_type = state.get("input_type", "text")
    if input_type == "organic" and not is_failed:
        organic_result = state.get("organic_result") or {}
        result_dict.update({
            "model_url": organic_result.get("model_url"),
            "stl_url": organic_result.get("stl_url"),
            "threemf_url": organic_result.get("threemf_url"),
            "mesh_stats": organic_result.get("mesh_stats"),
            "warnings": organic_result.get("warnings", []),
            "printability": organic_result.get("printability"),
        })

    # Include token stats in result (recalculate aggregates from stages)
    token_stats = state.get("token_stats")
    if token_stats:
        stages = token_stats.get("stages", [])
        token_stats["total_input_tokens"] = sum(s.get("input_tokens", 0) for s in stages)
        token_stats["total_output_tokens"] = sum(s.get("output_tokens", 0) for s in stages)
        token_stats["total_duration_s"] = round(sum(s.get("duration_s", 0) for s in stages), 3)
        result_dict["token_stats"] = token_stats

    if result_dict:
        orm_kwargs["result"] = result_dict

    await update_job(state["job_id"], **orm_kwargs)

    event_name = "job.failed" if is_failed else "job.completed"
    payload: dict[str, Any] = {"job_id": state["job_id"], "status": final_status}
    if is_failed:
        payload["error"] = state.get("error")
        payload["failure_reason"] = state.get("failure_reason")
    else:
        payload["model_url"] = state.get("model_url")
        payload["step_path"] = state.get("step_path")
        payload["printability"] = state.get("printability")
        if input_type == "organic":
            organic_result = state.get("organic_result") or {}
            payload.update({
                "stl_url": organic_result.get("stl_url"),
                "threemf_url": organic_result.get("threemf_url"),
                "mesh_stats": organic_result.get("mesh_stats"),
                "warnings": organic_result.get("warnings", []),
            })

    await _safe_dispatch(event_name, payload)
    return {"status": final_status}
