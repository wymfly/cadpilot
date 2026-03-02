"""DfAM vertex analysis graph node."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.graph.decorators import timed_node
from backend.graph.registry import register_node
from backend.graph.state import CadJobState

logger = logging.getLogger(__name__)


@register_node(
    name="analyze_dfam",
    display_name="DfAM分析",
    requires=[["step_model", "watertight_mesh"]],
    produces=["dfam_glb", "dfam_stats"],
    non_fatal=True,
)
@timed_node("analyze_dfam")
async def analyze_dfam_node(state: CadJobState) -> dict[str, Any]:
    """Run vertex-level DfAM analysis and export heatmap GLB.

    Catches all exceptions internally to ensure pipeline continuity.
    On failure, returns null results so check_printability falls back
    to global-level analysis.
    """
    step_path = state.get("step_path")
    job_id = state.get("job_id", "unknown")

    if not step_path:
        return {
            "dfam_glb_url": None,
            "dfam_stats": None,
            "_reasoning": {"skipped": "no step_path available"},
        }

    try:
        result = await asyncio.to_thread(_run_dfam_analysis, step_path, job_id)
        return result
    except Exception as exc:
        logger.warning("DfAM analysis failed (non-fatal): %s", exc, exc_info=True)
        return {
            "dfam_glb_url": None,
            "dfam_stats": None,
            "_reasoning": {"error": str(exc)},
        }


def _run_dfam_analysis(step_path: str, job_id: str) -> dict[str, Any]:
    """Synchronous DfAM analysis + GLB export (runs in thread)."""
    from pathlib import Path

    from backend.core.format_exporter import ExportConfig, FormatExporter
    from backend.core.vertex_analyzer import VertexAnalyzer

    import trimesh

    # Convert STEP -> temp STL for trimesh
    exporter = FormatExporter()
    stl_path = exporter._step_to_stl_temp(step_path, ExportConfig())

    try:
        # Run vertex analysis
        analyzer = VertexAnalyzer()
        analysis = analyzer.analyze(stl_path)

        # Load mesh for GLB export
        mesh = trimesh.load(stl_path, force="mesh")
    finally:
        import os
        try:
            os.unlink(stl_path)
        except OSError:
            pass

    # Build output path
    output_dir = Path(f"outputs/{job_id}")
    output_dir.mkdir(parents=True, exist_ok=True)
    glb_path = str(output_dir / "model_dfam.glb")

    # Prepare stats — compute at-risk counts from risk arrays (risk < 0.5)
    import numpy as np

    valid_thickness = analysis.wall_thickness[
        analysis.wall_thickness < VertexAnalyzer.SENTINEL_THICKNESS
    ]
    n_verts = len(mesh.vertices)
    n_wall_at_risk = int(np.sum(analysis.risk_wall < 0.5))
    n_overhang_at_risk = int(np.sum(analysis.risk_overhang < 0.5))

    wall_stats = {
        "analysis_type": "wall_thickness",
        "threshold": 1.0,
        "min_value": float(valid_thickness.min()) if len(valid_thickness) > 0 else None,
        "max_value": float(valid_thickness.max()) if len(valid_thickness) > 0 else None,
        "vertices_at_risk_count": n_wall_at_risk,
        "vertices_at_risk_percent": round(
            n_wall_at_risk / max(n_verts, 1) * 100, 1
        ),
    }
    overhang_stats = {
        "analysis_type": "overhang",
        "threshold": 45.0,
        "min_value": 0.0,
        "max_value": analysis.stats.get("overhang_max"),
        "vertices_at_risk_count": n_overhang_at_risk,
        "vertices_at_risk_percent": round(
            n_overhang_at_risk / max(n_verts, 1) * 100, 1
        ),
    }

    exporter.export_dfam_glb(
        mesh=mesh,
        risk_wall=analysis.risk_wall,
        risk_overhang=analysis.risk_overhang,
        wall_stats=wall_stats,
        overhang_stats=overhang_stats,
        output_path=glb_path,
    )

    dfam_glb_url = f"/outputs/{job_id}/model_dfam.glb"

    return {
        "dfam_glb_url": dfam_glb_url,
        "dfam_stats": {
            **analysis.stats,
            "wall_stats": wall_stats,
            "overhang_stats": overhang_stats,
        },
        "_reasoning": {
            "vertices_analyzed": analysis.stats.get("vertices_analyzed"),
            "wall_thickness_range": (
                f"{wall_stats.get('min_value')}-{wall_stats.get('max_value')} mm"
            ),
            "overhang_range": f"0-{overhang_stats.get('max_value')}°",
            "decimation_applied": analysis.stats.get("decimation_applied", False),
        },
    }
