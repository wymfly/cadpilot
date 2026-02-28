"""Lifecycle nodes: create_job, confirm_with_user, finalize."""

from __future__ import annotations

import asyncio
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
        result = adispatch_custom_event(event_name, payload)
        if asyncio.iscoroutine(result):
            await result
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
    return {"status": "created"}


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
    direct_fields = ["intent", "drawing_spec", "error", "result"]
    for field in direct_fields:
        val = state.get(field)
        if val is not None:
            orm_kwargs[field] = val

    for state_key, orm_col in STATE_TO_ORM_MAPPING.items():
        val = state.get(state_key)
        if val is not None:
            orm_kwargs[orm_col] = val

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

    await _safe_dispatch(event_name, payload)
    return {"status": final_status}
