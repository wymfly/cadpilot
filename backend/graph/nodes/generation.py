"""Generation nodes: text (template) and drawing (VL pipeline) paths."""

import asyncio
import logging
import tempfile
from pathlib import Path
from string import Template
from typing import Any

from backend.core.candidate_scorer import score_candidate
from backend.core.modeling_strategist import ModelingStrategist
from backend.core.spec_compiler import CompilationError, SpecCompiler
from backend.core.validators import cross_section_analysis, validate_step_geometry
from backend.graph.chains import build_code_gen_chain
from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.registry import register_node
from backend.graph.state import CadJobState
from backend.graph.subgraphs.refiner import (
    build_refiner_subgraph,
    map_job_to_refiner,
    map_refiner_to_job,
)
from backend.infra.sandbox import SafeExecutor
from backend.knowledge.part_types import DrawingSpec
from backend.models.pipeline_config import PipelineConfig
from backend.pipeline.pipeline import _score_geometry

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path("outputs").resolve()
GENERATION_TIMEOUT_S = 300.0  # Heavyweight node timeout


@register_node(name="generate_step_text", display_name="文本→STEP生成",
    requires=["confirmed_params"], produces=["step_model"], input_types=["text"])
async def generate_step_text_node(state: CadJobState) -> dict[str, Any]:
    """Generate STEP from text intent via SpecCompiler (template-first, LLM-fallback)."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {"_reasoning": {"skip": "idempotent, STEP already exists"}}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    matched = state.get("matched_template")

    # Business event: frontend shows "Generating..." phase
    await _safe_dispatch("job.generating", {
        "job_id": state["job_id"], "status": "generating",
        "message": f"正在生成 STEP 模型（模板: {matched or 'LLM'}）",
    })

    try:
        compiler = SpecCompiler()
        result = await asyncio.to_thread(
            compiler.compile,
            matched_template=matched,
            params=state.get("confirmed_params") or {},
            output_path=step_path,
            input_text=state.get("input_text") or "",
            intent=state.get("intent"),
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Text generation failed: %s (%s)", exc, reason)
        await _safe_dispatch(
            "job.failed",
            {"job_id": state["job_id"], "error": str(exc), "failure_reason": reason, "status": "failed"},
        )
        return {
            "error": str(exc), "failure_reason": reason, "status": "failed",
            "_reasoning": {"error": str(exc)},
        }

    # Persist generated code to file
    code_text = result.cadquery_code or ""
    if code_text:
        code_path = job_dir / "code.py"
        code_path.write_text(code_text, encoding="utf-8")

    return {
        "step_path": result.step_path,
        "generated_code": code_text or None,
        "status": "generating",
        "_reasoning": {
            "method": result.method,
            "template": result.template_name or "N/A",
            "step_path": result.step_path,
        },
    }


async def _orchestrate_drawing_generation(state: dict, config: dict) -> dict:
    """Orchestrate strategy → codegen → execute → refine → post-check.

    Separated from node function for testability.
    Node handles state mapping, SSE dispatch, and exception wrapping.
    """
    pipeline_config: PipelineConfig = config.get("configurable", {}).get(
        "pipeline_config", PipelineConfig()
    )
    spec = state.get("confirmed_spec") or state.get("drawing_spec")
    if isinstance(spec, dict):
        spec = DrawingSpec(**spec)

    step_path = state["step_path"]

    # Stage 1.5: Strategy selection (pure rule engine, no LLM)
    strategist = ModelingStrategist()
    context = strategist.select(spec)
    if pipeline_config.api_whitelist:
        from backend.core.api_whitelist import get_whitelist_prompt_section
        context.strategy += "\n\n" + get_whitelist_prompt_section()

    # Stage 2: Code generation via LCEL chain
    chain = build_code_gen_chain()
    modeling_input = {"modeling_context": context.to_prompt_text()}

    if pipeline_config.best_of_n > 1:
        # Phase 1: LLM concurrent
        codes = await asyncio.gather(
            *[chain.ainvoke(modeling_input) for _ in range(pipeline_config.best_of_n)],
            return_exceptions=True,
        )
        # Phase 2: Execute serial, pick highest scorer
        best_code, best_score = None, -1.0
        for raw_code in codes:
            if isinstance(raw_code, Exception) or raw_code is None:
                continue
            candidate_code = Template(raw_code).safe_substitute(output_filename=step_path)
            executor = SafeExecutor(timeout_s=60)
            exec_result = executor.execute(candidate_code)
            if exec_result.success:
                compiled, vol, bbox, topo = _score_geometry(step_path, spec, pipeline_config)
                sc = float(score_candidate(compiled=compiled, volume_ok=vol, bbox_ok=bbox, topology_ok=topo))
                if sc > best_score:
                    best_code, best_score = candidate_code, sc
        code = best_code
    else:
        raw = await chain.ainvoke(modeling_input)
        code = Template(raw).safe_substitute(output_filename=step_path) if raw else None

    if code is None:
        return {"status": "failed", "failure_reason": "generation_error", "error": "Code generation failed"}

    # Stage 3: Execute code
    executor = SafeExecutor()
    executor.execute(code)

    # Stage 3.5: Geometry validation (informational)
    validate_step_geometry(step_path)

    # Stage 4: Refiner subgraph
    refiner = build_refiner_subgraph()
    refiner_input = map_job_to_refiner(
        {"generated_code": code, "step_path": step_path, "drawing_spec": spec, "image_path": state.get("image_path", "")},
        config,
    )
    refiner_result = await refiner.ainvoke(refiner_input, config=config)
    updates = map_refiner_to_job(refiner_result)

    # Stage 5: Post-checks
    if pipeline_config.cross_section_check:
        try:
            cross_section_analysis(step_path, spec)
        except Exception:
            pass

    return {
        "step_path": step_path,
        "generated_code": updates.get("generated_code", code),
    }


@register_node(name="generate_step_drawing", display_name="图纸→STEP生成",
    requires=["confirmed_params"], produces=["step_model"], input_types=["drawing"])
async def generate_step_drawing_node(state: CadJobState, config: dict = None) -> dict[str, Any]:
    """Generate STEP from confirmed DrawingSpec via LCEL chains + refiner subgraph."""
    # Idempotent: skip if already generated
    existing = state.get("step_path")
    if existing and Path(existing).exists():
        return {"_reasoning": {"skip": "idempotent, STEP already exists"}}

    job_dir = OUTPUTS_DIR / state["job_id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    step_path = str(job_dir / "model.step")

    image_path = state.get("image_path")
    if not image_path:
        await _safe_dispatch("job.failed", {
            "job_id": state["job_id"], "error": "No image_path provided",
            "failure_reason": "generation_error", "status": "failed",
        })
        return {
            "error": "No image_path provided", "failure_reason": "generation_error", "status": "failed",
            "_reasoning": {"error": "No image_path provided"},
        }

    await _safe_dispatch("job.generating", {
        "job_id": state["job_id"], "status": "generating",
        "message": "正在生成 STEP 模型（LCEL pipeline）",
    })

    try:
        result = await asyncio.wait_for(
            _orchestrate_drawing_generation({**state, "step_path": step_path}, config or {}),
            timeout=GENERATION_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        await _safe_dispatch("job.failed", {
            "job_id": state["job_id"], "error": "图纸生成超时",
            "failure_reason": "timeout", "status": "failed",
        })
        return {"error": "图纸生成超时", "failure_reason": "timeout", "status": "failed"}
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        logger.error("Drawing generation failed: %s (%s)", exc, reason)
        await _safe_dispatch("job.failed", {
            "job_id": state["job_id"], "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    # Persist code
    code_text = result.get("generated_code", "")
    if code_text:
        (job_dir / "code.py").write_text(code_text, encoding="utf-8")

    return {
        "step_path": result.get("step_path", step_path),
        "generated_code": code_text or None,
        "status": "generating",
    }
