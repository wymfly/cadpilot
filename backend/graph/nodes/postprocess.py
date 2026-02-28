"""Postprocess nodes: STEP->GLB preview, printability check."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)

PREVIEW_TIMEOUT_S = 30.0


def _convert_step_to_glb(step_path: str) -> str | None:
    """Synchronous STEP->GLB conversion — delegates to existing logic."""
    from backend.api.generate import _convert_step_to_glb as _orig

    glb_path = str(Path(step_path).with_suffix(".glb"))
    _orig(step_path, glb_path)
    return glb_path


def _run_printability_check(step_path: str) -> dict | None:
    """Synchronous printability check — delegates to existing logic."""
    from backend.api.generate import _run_printability_check as _orig

    return _orig(step_path)


async def convert_preview_node(state: CadJobState) -> dict[str, Any]:
    """Convert STEP to GLB for 3D preview (non-fatal on failure)."""
    step_path = state.get("step_path")
    if not step_path:
        return {}

    try:
        glb_path = await asyncio.wait_for(
            asyncio.to_thread(_convert_step_to_glb, step_path),
            timeout=PREVIEW_TIMEOUT_S,
        )
    except Exception as exc:
        logger.warning("GLB preview conversion failed (non-fatal): %s", exc)
        return {"model_url": None}

    model_url = f"/outputs/{state['job_id']}/model.glb" if glb_path else None
    await _safe_dispatch(
        "job.preview_ready",
        {"job_id": state["job_id"], "model_url": model_url},
    )
    return {"model_url": model_url}


async def check_printability_node(state: CadJobState) -> dict[str, Any]:
    """Run DfAM printability analysis (non-fatal on failure)."""
    step_path = state.get("step_path")
    if not step_path:
        return {}

    try:
        result = await asyncio.to_thread(_run_printability_check, step_path)
    except Exception as exc:
        logger.warning("Printability check failed (non-fatal): %s", exc)
        return {"printability": None}

    await _safe_dispatch(
        "job.printability_ready",
        {"job_id": state["job_id"], "printability": result},
    )
    return {"printability": result}
