"""PipelineState — the new state schema for plugin-based pipeline nodes.

Key design: assets and data use custom dict-merge reducers so that
each node only returns its incremental additions, and LangGraph merges
them instead of overwriting.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def _merge_dicts(existing: dict, update: dict) -> dict:
    """Custom reducer: shallow-merge dicts instead of overwrite."""
    return {**existing, **update}


class PipelineState(TypedDict, total=False):
    # ── Core ──
    job_id: str
    input_type: str  # "text" | "drawing" | "organic"

    # ── New plugin pipeline fields ──
    assets: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    data: Annotated[dict[str, Any], _merge_dicts]
    pipeline_config: dict[str, dict[str, Any]]
    node_trace: Annotated[list[dict[str, Any]], operator.add]

    # ── Legacy CadJobState fields (backward compat during migration) ──
    input_text: str | None
    image_path: str | None
    intent: dict | None
    matched_template: str | None
    drawing_spec: dict | None
    confirmed_params: dict | None
    confirmed_spec: dict | None
    disclaimer_accepted: bool
    base_body_method: str | None
    step_path: str | None
    generated_code: str | None
    model_url: str | None
    printability: dict | None
    recommendations: list[dict] | None
    dfam_glb_url: str | None
    dfam_stats: dict | None
    organic_spec: dict | None
    organic_provider: str | None
    organic_quality_mode: str | None
    organic_reference_image: str | None
    organic_constraints: dict | None
    raw_mesh_path: str | None
    mesh_stats: dict | None
    organic_warnings: Annotated[list[str], operator.add]
    organic_result: dict | None
    parent_job_id: str | None
    token_stats: dict | None
    corrections: list[dict] | None

    # ── Status & error ──
    status: str
    error: str | None
    failure_reason: str | None
