"""CadJobState — the single state object flowing through the CAD Job StateGraph."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class CadJobState(TypedDict, total=False):
    # ── Input ──
    job_id: str
    input_type: str              # "text" | "drawing" | "organic"
    input_text: str | None
    image_path: str | None

    # ── Analysis outputs ──
    intent: dict | None          # IntentSpec.model_dump()
    matched_template: str | None
    drawing_spec: dict | None    # DrawingSpec.model_dump()

    # ── HITL confirmation inputs ──
    confirmed_params: dict | None
    confirmed_spec: dict | None
    disclaimer_accepted: bool

    # ── Generation outputs ──
    step_path: str | None
    generated_code: str | None   # CadQuery Python source code
    model_url: str | None        # GLB preview URL
    printability: dict | None
    recommendations: list[dict] | None  # ParamRecommendation / PostProcessRecommendation

    # ── DfAM analysis outputs ──
    dfam_glb_url: str | None
    dfam_stats: dict | None

    # ── Organic outputs ──
    organic_spec: dict | None            # OrganicSpec.model_dump()
    organic_provider: str | None         # "auto" | "tripo3d" | "hunyuan3d"
    organic_quality_mode: str | None     # "draft" | "standard" | "high"
    organic_reference_image: str | None  # uploaded file_id
    organic_constraints: dict | None     # {bounding_box, engineering_cuts}
    raw_mesh_path: str | None
    mesh_stats: dict | None
    organic_warnings: Annotated[list[str], operator.add]
    organic_result: dict | None          # {model_url, stl_url, threemf_url, ...}

    # ── Version chain ──
    parent_job_id: str | None    # parent Job for forked text generations

    # ── Pipeline configuration ──
    pipeline_config: dict | None  # PipelineConfig.model_dump()
    pipeline_config_updates: dict | None  # HITL updates from confirm
    token_stats: dict | None      # TokenTracker.get_stats()

    # ── Status & error ──
    status: str                  # mirrors JobStatus value
    error: str | None
    failure_reason: str | None   # typed: timeout | rate_limited | invalid_json | generation_error


# Maps CadJobState field names → ORM JobModel column names where they differ.
STATE_TO_ORM_MAPPING: dict[str, str] = {
    "confirmed_spec": "drawing_spec_confirmed",
    "printability": "printability_result",
    # step_path and model_url are assembled into the ORM `result` JSON column
    # by finalize_node — no direct 1:1 mapping needed here.
    # organic_spec is saved to DB directly in analyze_organic_node,
    # organic_result is assembled into `result` JSON column by finalize_node.
}
