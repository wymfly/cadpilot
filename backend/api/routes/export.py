"""Asset export endpoint — download pipeline artifacts with optional format conversion.

GET /api/jobs/{job_id}/assets/{asset_key}?format=stl
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from backend.core.mesh_converter import convert_mesh
from backend.graph.context import AssetRegistry

router = APIRouter(tags=["export"])


def _get_asset_registry(job_id: str) -> AssetRegistry | None:
    """Retrieve the AssetRegistry for a given job from the LangGraph checkpointer.

    Returns ``None`` when the job does not exist or has no checkpoint.
    This function is designed to be patched in tests.
    """
    # Production path: query LangGraph checkpointer for job state
    try:
        from backend.graph import get_compiled_graph_sync

        graph = get_compiled_graph_sync()
        config = {"configurable": {"thread_id": job_id}}
        state = graph.get_state(config)
        if state is None or state.values is None:
            return None
        assets_dict: dict[str, Any] = state.values.get("assets", {})
        if not assets_dict:
            return None
        return AssetRegistry.from_dict(assets_dict)
    except Exception:
        return None


@router.get("/jobs/{job_id}/assets/{asset_key}")
async def export_asset(
    job_id: str,
    asset_key: str,
    background_tasks: BackgroundTasks,
    format: str | None = Query(default=None),  # noqa: A002
) -> FileResponse:
    """Export a pipeline asset, optionally converting to a different mesh format.

    Parameters
    ----------
    job_id:
        Pipeline job identifier.
    asset_key:
        Asset key as registered in the pipeline AssetRegistry.
    format:
        Target mesh format (obj, glb, stl, 3mf). ``None`` returns the
        original file without conversion.
    """
    # Locate asset registry for this job
    registry = _get_asset_registry(job_id)
    if registry is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    if not registry.has(asset_key):
        raise HTTPException(
            status_code=404,
            detail=f"Asset not found: {asset_key}",
        )

    entry = registry.get(asset_key)
    asset_path = Path(entry.path)

    # Handle file:// URI scheme
    if entry.path.startswith("file://"):
        from urllib.parse import unquote

        asset_path = Path(unquote(entry.path[7:]))

    if not asset_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Asset file not found on disk: {asset_key}",
        )

    # No format conversion requested → return original
    if format is None:
        return FileResponse(path=str(asset_path), filename=asset_path.name)

    # Format conversion
    tmp_dir = tempfile.mkdtemp()
    try:
        converted = await asyncio.to_thread(
            convert_mesh, asset_path, format, Path(tmp_dir),
        )
    except ValueError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Schedule cleanup after response is sent
    background_tasks.add_task(shutil.rmtree, tmp_dir)

    return FileResponse(path=str(converted), filename=converted.name)
