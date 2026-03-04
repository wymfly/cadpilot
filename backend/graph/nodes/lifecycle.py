"""Lifecycle nodes: create_job, confirm_with_user, finalize."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import adispatch_custom_event

from backend.graph.registry import register_node
from backend.graph.state import CadJobState, STATE_TO_ORM_MAPPING
from backend.models.job import create_job, get_job, update_job

logger = logging.getLogger(__name__)


def _merge_asset_results(
    result_dict: dict[str, Any],
    assets: dict[str, Any],
    state: dict[str, Any],
) -> None:
    """Merge new-architecture asset registry data into the result dict.

    Reads from the ``assets`` dict (serialized AssetRegistry entries)
    to populate model_url, stl_url, gcode_url, mesh_stats, etc.
    Falls back to state-level fields when assets lack certain data.
    """
    # Best mesh for model_url: final_mesh > scaled_mesh > watertight_mesh > raw_mesh
    model_url = None
    for key in ("final_mesh", "scaled_mesh", "watertight_mesh", "raw_mesh"):
        asset = assets.get(key)
        if asset:
            path = asset.get("path", "") if isinstance(asset, dict) else ""
            if path:
                model_url = path
                break
    result_dict["model_url"] = model_url

    # STL URL: check for explicit stl asset or derive from final_mesh
    stl_asset = assets.get("stl_export")
    if stl_asset:
        result_dict["stl_url"] = stl_asset.get("path") if isinstance(stl_asset, dict) else None
    else:
        result_dict["stl_url"] = None

    # G-code bundle
    gcode_asset = assets.get("gcode_bundle")
    if gcode_asset:
        result_dict["gcode_url"] = gcode_asset.get("path") if isinstance(gcode_asset, dict) else None
        metadata = gcode_asset.get("metadata", {}) if isinstance(gcode_asset, dict) else {}
        if metadata:
            result_dict["gcode_metadata"] = metadata

    # Mesh stats from data dict or asset metadata
    data = state.get("data") or {}
    mesh_stats = data.get("mesh_stats")
    if not mesh_stats:
        # Try to get from watertight_mesh or final_mesh metadata
        for key in ("final_mesh", "watertight_mesh"):
            asset = assets.get(key)
            if asset and isinstance(asset, dict):
                meta = asset.get("metadata", {})
                if meta:
                    mesh_stats = meta
                    break
    result_dict["mesh_stats"] = mesh_stats

    # Warnings from data dict
    result_dict["warnings"] = data.get("warnings", [])

    # Printability from state
    result_dict["printability"] = state.get("printability")


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
    except Exception as exc:
        logger.warning("Event dispatch failed for %s: %s", event_name, exc)


# NOTE: @timed_node decorators for lifecycle nodes are applied in builder.py
# to avoid circular import (decorators.py imports _safe_dispatch from here).


@register_node(name="create_job", display_name="创建任务",
    is_entry=True, produces=["job_info"])
async def create_job_node(state: CadJobState) -> dict[str, Any]:
    """Create DB Job record and dispatch job.created event."""
    # Check if job already exists (breakpoint mode pre-creates in API layer)
    existing = await get_job(state["job_id"])
    if existing is None:
        await create_job(
            job_id=state["job_id"],
            input_type=state["input_type"],
            input_text=state.get("input_text") or "",
        )
    # Persist optional fields to DB
    extra_updates: dict[str, Any] = {}
    if state.get("image_path"):
        extra_updates["image_path"] = state["image_path"]
    if state.get("parent_job_id"):
        extra_updates["parent_job_id"] = state["parent_job_id"]
    if extra_updates:
        await update_job(state["job_id"], **extra_updates)

    # Initialize token tracker (serialized as dict in state)
    from backend.infra.token_tracker import TokenTracker

    tracker = TokenTracker()

    # Business event: frontend needs status="created" to set jobId early
    await _safe_dispatch("job.created", {
        "job_id": state["job_id"],
        "input_type": state["input_type"],
        "status": "created",
        "message": f"任务已创建 (类型: {state['input_type']})",
    })

    return {
        "status": "created",
        "token_stats": tracker.get_stats(),
        "_reasoning": {"input_routing": f"input_type={state['input_type']}"},
    }


@register_node(name="confirm_with_user", display_name="用户确认",
    supports_hitl=True,
    requires=[["intent_spec", "drawing_spec", "organic_spec"]],
    produces=["confirmed_params"])
async def confirm_with_user_node(state: CadJobState) -> dict[str, Any]:
    """Process Command(resume=...) data after interrupt.

    By the time this node executes, LangGraph has already merged the
    resume payload into state (confirmed_params / confirmed_spec / disclaimer_accepted).
    We advance the status and merge any pipeline_config_updates into pipeline_config.
    """
    result: dict[str, Any] = {"status": "confirmed", "_reasoning": {"confirmation": "user confirmed parameters"}}

    # Merge pipeline_config_updates into pipeline_config for runtime skip
    updates = state.get("pipeline_config_updates")
    if updates:
        import copy
        current_config = copy.deepcopy(state.get("pipeline_config") or {})
        for node_name, node_updates in updates.items():
            current_config.setdefault(node_name, {}).update(node_updates)
        result["pipeline_config"] = current_config

    return result


@register_node(
    name="finalize",
    display_name="完成",
    is_terminal=True,
    produces=[],
)
async def finalize_node(state: CadJobState) -> dict[str, Any]:
    """Write final state to DB and dispatch terminal event."""
    is_failed = state.get("error") is not None or state.get("status") == "failed"
    final_status = "failed" if is_failed else "completed"

    # Build ORM update kwargs using STATE_TO_ORM_MAPPING
    orm_kwargs: dict[str, Any] = {"status": final_status}
    direct_fields = ["intent", "drawing_spec", "error", "generated_code", "parent_job_id"]
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
        # New architecture: read from AssetRegistry (assets dict in state)
        assets = state.get("assets") or {}
        if assets and any(k in assets for k in ("raw_mesh", "watertight_mesh", "final_mesh", "gcode_bundle")):
            _merge_asset_results(result_dict, assets, state)
        else:
            # Legacy fallback: read from organic_result dict
            organic_result = state.get("organic_result") or {}
            result_dict.update({
                "model_url": organic_result.get("model_url"),
                "stl_url": organic_result.get("stl_url"),
                "threemf_url": organic_result.get("threemf_url"),
                "mesh_stats": organic_result.get("mesh_stats"),
                "warnings": organic_result.get("warnings", []),
                "printability": organic_result.get("printability"),
            })

    if state.get("recommendations"):
        result_dict["recommendations"] = state["recommendations"]

    # Include token stats in result (pass through as-is; per-node timing
    # is now in node.completed SSE events via @timed_node decorator)
    token_stats = state.get("token_stats")
    if token_stats:
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
        payload["model_url"] = result_dict.get("model_url") or state.get("model_url")
        payload["step_path"] = state.get("step_path")
        payload["printability"] = result_dict.get("printability") or state.get("printability")
        payload["recommendations"] = state.get("recommendations")
        if input_type == "organic":
            # Prefer result_dict (populated from AssetRegistry or organic_result)
            payload["stl_url"] = result_dict.get("stl_url")
            payload["mesh_stats"] = result_dict.get("mesh_stats")
            payload["warnings"] = result_dict.get("warnings", [])
            payload["gcode_url"] = result_dict.get("gcode_url")

    await _safe_dispatch(event_name, payload)
    return {
        "status": final_status,
        "_reasoning": {"final_status": final_status},
    }
