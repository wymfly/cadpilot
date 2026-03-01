"""Postprocess nodes: STEP->GLB preview, printability check."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.graph.decorators import timed_node
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

PREVIEW_TIMEOUT_S = 30.0


def _convert_step_to_glb(step_path: str) -> str | None:
    """Synchronous STEP->GLB conversion — delegates to existing logic."""
    from backend.pipeline.vision_cad_pipeline import _convert_step_to_glb as _orig

    glb_path = str(Path(step_path).with_suffix(".glb"))
    _orig(step_path, glb_path)
    return glb_path


def _run_printability_check(step_path: str) -> dict | None:
    """Synchronous printability check — delegates to existing logic."""
    from backend.pipeline.vision_cad_pipeline import _run_printability_check as _orig

    return _orig(step_path)


@timed_node("convert_preview")
async def convert_preview_node(state: CadJobState) -> dict[str, Any]:
    """Convert STEP to GLB for 3D preview (non-fatal on failure)."""
    step_path = state.get("step_path")
    if not step_path:
        return {"_reasoning": {"result": "跳过", "format": "GLB"}}

    try:
        glb_path = await asyncio.wait_for(
            asyncio.to_thread(_convert_step_to_glb, step_path),
            timeout=PREVIEW_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("GLB preview conversion failed (non-fatal): %s", exc)
        return {"model_url": None, "_reasoning": {"result": f"失败: {exc}", "format": "GLB"}}

    model_url = f"/outputs/{state['job_id']}/model.glb" if glb_path else None
    return {
        "model_url": model_url,
        "_reasoning": {
            "format": "GLB",
            "result": "成功" if glb_path else "跳过",
        },
    }


@timed_node("check_printability")
async def check_printability_node(state: CadJobState) -> dict[str, Any]:
    """Run DfAM printability analysis (non-fatal on failure)."""
    step_path = state.get("step_path")
    if not step_path:
        return {"_reasoning": {"printable": "检查跳过", "issues_count": "0", "recommendations_count": "0"}}

    try:
        result = await asyncio.to_thread(_run_printability_check, step_path)
    except Exception as exc:
        logger.warning("Printability check failed (non-fatal): %s", exc)
        return {"printability": None, "_reasoning": {"printable": f"检查失败: {exc}", "issues_count": "0", "recommendations_count": "0"}}

    # Generate post-processing recommendations
    from backend.core.recommendation_engine import generate_recommendations

    new_recs = generate_recommendations(result)
    rec_dicts = [
        {"action": r.action, "tool": r.tool, "description": r.description, "severity": r.severity}
        for r in new_recs
    ]

    # Merge with existing recommendations from analysis phase (dedup by action)
    existing_recs = list(state.get("recommendations") or [])
    seen_actions = {r.get("action") for r in existing_recs if r.get("action")}
    deduped_new = [r for r in rec_dicts if r.get("action") not in seen_actions]
    all_recs = existing_recs + deduped_new

    _reasoning = {
        "printable": str(result.get("printable", "N/A")) if result else "检查跳过",
        "issues_count": str(len(result.get("issues", []))) if result else "0",
        "recommendations_count": str(len(all_recs)),
    }

    # Intercept error-level printability issues to fail the pipeline
    if result and not result.get("printable", True):
        error_issues = [
            issue
            for issue in result.get("issues", [])
            if issue.get("severity") == "error"
        ]
        if error_issues:
            error_msgs = "; ".join(issue.get("message", "") for issue in error_issues)
            return {
                "printability": result,
                "recommendations": all_recs,
                "error": f"Printability check failed: {error_msgs}",
                "failure_reason": "printability_error",
                "status": "failed",
                "_reasoning": _reasoning,
            }

    return {"printability": result, "recommendations": all_recs, "_reasoning": _reasoning}
