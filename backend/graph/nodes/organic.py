"""Organic graph nodes: spec building, mesh generation, post-processing."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from backend.core.organic_spec_builder import OrganicSpecBuilder
from backend.graph.llm_utils import map_exception_to_failure_reason
from backend.graph.nodes.lifecycle import _safe_dispatch
from backend.graph.state import CadJobState
from backend.models.job import update_job as _update_job
from backend.models.organic import OrganicConstraints, OrganicGenerateRequest

logger = logging.getLogger(__name__)

LLM_TIMEOUT_S = 60


async def _safe_update_job(job_id: str, **kwargs: Any) -> None:
    """Update DB job, tolerating missing records (e.g. in unit tests)."""
    try:
        await _update_job(job_id, **kwargs)
    except (KeyError, Exception) as exc:
        logger.debug("_safe_update_job(%s) skipped: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Node 1: Analyze organic input → build OrganicSpec via LLM
# ---------------------------------------------------------------------------


async def analyze_organic_node(state: CadJobState) -> dict[str, Any]:
    """Build OrganicSpec via LLM, dispatch spec_ready event, pause for HITL."""
    job_id = state["job_id"]
    input_text = state.get("input_text") or ""
    constraints_raw = state.get("organic_constraints")
    quality_mode = state.get("organic_quality_mode") or "standard"

    # Build OrganicGenerateRequest from state
    constraints = OrganicConstraints(**(constraints_raw or {}))
    request = OrganicGenerateRequest(
        prompt=input_text,
        reference_image=state.get("organic_reference_image"),
        constraints=constraints,
        quality_mode=quality_mode,
        provider=state.get("organic_provider") or "auto",
    )

    builder = OrganicSpecBuilder()
    try:
        spec = await asyncio.wait_for(builder.build(request), timeout=LLM_TIMEOUT_S)
    except asyncio.TimeoutError:
        error_msg = f"Organic spec 构建超时（{LLM_TIMEOUT_S}s）"
        await _safe_update_job(job_id, status="failed", error=error_msg)
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": error_msg,
            "failure_reason": "timeout", "status": "failed",
        })
        return {"error": error_msg, "failure_reason": "timeout", "status": "failed"}
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    spec_dict = spec.model_dump()

    # Dispatch spec_ready event with full spec for frontend confirmation UI
    await _safe_dispatch("job.organic_spec_ready", {
        "job_id": job_id,
        "organic_spec": spec_dict,
        "status": "organic_spec_ready",
    })

    # Persist to DB so GET /api/v1/jobs/{id} returns spec on page refresh
    await _safe_update_job(job_id, status="awaiting_confirmation", organic_spec=spec_dict)
    await _safe_dispatch("job.awaiting_confirmation", {
        "job_id": job_id, "status": "awaiting_confirmation",
    })

    return {"organic_spec": spec_dict, "status": "awaiting_confirmation"}


# ---------------------------------------------------------------------------
# Node 2: Generate raw mesh via provider API
# ---------------------------------------------------------------------------


async def generate_organic_mesh_node(state: CadJobState) -> dict[str, Any]:
    """Create MeshProvider, generate raw mesh, dispatch progress events."""
    job_id = state["job_id"]

    # Idempotent: skip if mesh already exists
    raw_mesh = state.get("raw_mesh_path")
    if raw_mesh and Path(raw_mesh).exists():
        logger.info("Mesh already exists at %s, skipping generation", raw_mesh)
        return {}

    from backend.infra.mesh_providers import AutoProvider, HunyuanProvider, TripoProvider
    from backend.models.organic import OrganicSpec

    provider_name = state.get("organic_provider") or "auto"
    spec_dict = state.get("organic_spec") or {}
    spec = OrganicSpec(**spec_dict)

    # Read reference image if uploaded
    reference_image_bytes: bytes | None = None
    ref_id = state.get("organic_reference_image")
    if ref_id:
        reference_image_bytes = await _load_reference_image(ref_id)

    await _safe_dispatch("job.generating", {
        "job_id": job_id, "stage": "mesh_generation", "status": "generating",
    })
    await _safe_update_job(job_id, status="generating")

    # Instantiate provider with config from Settings.
    from backend.config import Settings as _Settings

    _settings = _Settings()
    _output_dir = Path("outputs") / "organic"

    if provider_name == "tripo3d":
        provider = TripoProvider(api_key=_settings.tripo3d_api_key, output_dir=_output_dir)
    elif provider_name == "hunyuan3d":
        provider = HunyuanProvider(api_key=_settings.hunyuan3d_api_key, output_dir=_output_dir)
    else:
        provider = AutoProvider(
            tripo=TripoProvider(api_key=_settings.tripo3d_api_key, output_dir=_output_dir),
            hunyuan=HunyuanProvider(api_key=_settings.hunyuan3d_api_key, output_dir=_output_dir),
        )

    # Bridge sync on_progress callback to dispatch keepalive SSE events.
    # provider.generate() may run sync loops internally; use sync dispatch.
    loop = asyncio.get_running_loop()

    def _on_progress(stage: str, progress: float) -> None:
        """Sync callback safe to call from provider's internal thread."""
        asyncio.run_coroutine_threadsafe(
            _safe_dispatch("job.generating", {
                "job_id": job_id, "stage": stage, "progress": progress,
                "status": "generating",
            }),
            loop,
        )

    try:
        result_path = await provider.generate(
            spec, reference_image=reference_image_bytes, on_progress=_on_progress,
        )
    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}

    return {"raw_mesh_path": str(result_path), "status": "generating"}


async def _load_reference_image(file_id: str) -> bytes | None:
    """Load uploaded reference image by file_id."""
    upload_dir = Path("outputs") / "organic" / "uploads"
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = upload_dir / f"{file_id}{ext}"
        if path.exists():
            return await asyncio.to_thread(path.read_bytes)
    logger.warning("Reference image not found for file_id=%s", file_id)
    return None


# ---------------------------------------------------------------------------
# Node 3: Post-process mesh (repair, scale, boolean, validate, export)
# ---------------------------------------------------------------------------


async def postprocess_organic_node(state: CadJobState) -> dict[str, Any]:
    """Run full post-processing pipeline via asyncio.to_thread for CPU-bound ops."""
    job_id = state["job_id"]
    raw_mesh_path = state.get("raw_mesh_path")
    if not raw_mesh_path:
        return {"error": "No raw_mesh_path in state", "status": "failed"}

    spec_dict = state.get("organic_spec") or {}
    quality_mode = state.get("organic_quality_mode") or "standard"
    warnings: list[str] = []

    from backend.core.mesh_post_processor import MeshPostProcessor

    job_dir = Path("outputs") / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    async def _dispatch_step(step: str, step_status: str, message: str = "",
                             progress: float = 0.0) -> None:
        await _safe_dispatch("job.post_processing", {
            "job_id": job_id, "step": step, "step_status": step_status,
            "message": message, "progress": progress,
        })

    try:
        # 1. Load
        await _dispatch_step("load", "running", "Loading mesh...")
        mesh = await asyncio.to_thread(MeshPostProcessor.load_mesh, Path(raw_mesh_path))
        await _dispatch_step("load", "success", "Mesh loaded", 0.15)

        # 2. Repair
        await _dispatch_step("repair", "running", "Repairing mesh...")
        mesh, repair_info = await asyncio.to_thread(MeshPostProcessor.repair_mesh, mesh)
        if repair_info.status == "degraded":
            warnings.append(f"Mesh repair degraded: {repair_info.message}")
        await _dispatch_step("repair", "success", repair_info.message, 0.30)

        # 3. Scale
        target_bbox = spec_dict.get("final_bounding_box")
        if target_bbox:
            await _dispatch_step("scale", "running", "Scaling mesh...")
            mesh = await asyncio.to_thread(
                MeshPostProcessor.scale_mesh, mesh, tuple(target_bbox),
            )
            await _dispatch_step("scale", "success", "Mesh scaled", 0.45)
        else:
            await _dispatch_step("scale", "skipped", "No target bounding box", 0.45)

        # 4. Boolean cuts
        engineering_cuts = spec_dict.get("engineering_cuts", [])
        boolean_cuts_applied = 0
        if quality_mode == "draft" or not engineering_cuts:
            await _dispatch_step("boolean", "skipped", "Draft mode or no cuts", 0.60)
        else:
            await _dispatch_step("boolean", "running", "Applying boolean cuts...")
            try:
                mesh, cuts_applied, cut_warnings = await asyncio.to_thread(
                    MeshPostProcessor.apply_boolean_cuts, mesh, engineering_cuts,
                )
                boolean_cuts_applied = cuts_applied
                warnings.extend(cut_warnings)
                await _dispatch_step("boolean", "success",
                                     f"{cuts_applied} cuts applied", 0.60)
            except Exception as exc:
                warnings.append(f"Boolean cuts failed: {exc}")
                await _dispatch_step("boolean", "failed", str(exc), 0.60)

        # 5. Validate
        await _dispatch_step("validate", "running", "Validating mesh...")
        stats = await asyncio.to_thread(
            MeshPostProcessor.validate_mesh, mesh, boolean_cuts_applied,
        )
        stats_dict = stats.model_dump()
        await _dispatch_step("validate", "success", "Mesh valid", 0.75)

        # 6. Export GLB/STL/3MF
        await _dispatch_step("export", "running", "Exporting formats...")
        glb_path = job_dir / "model.glb"
        stl_path = job_dir / "model.stl"
        threemf_path = job_dir / "model.3mf"

        await asyncio.to_thread(mesh.export, str(glb_path), file_type="glb")
        await asyncio.to_thread(mesh.export, str(stl_path), file_type="stl")

        threemf_url: str | None = None
        try:
            await asyncio.to_thread(mesh.export, str(threemf_path), file_type="3mf")
            threemf_url = f"/outputs/{job_id}/model.3mf"
        except Exception as exc:
            warnings.append(f"3MF export failed: {exc}")

        model_url = f"/outputs/{job_id}/model.glb"
        stl_url = f"/outputs/{job_id}/model.stl"
        await _dispatch_step("export", "success", "Export complete", 0.90)

        # 7. Printability check (uses geometry_info dict from mesh stats)
        printability_result: dict | None = None
        try:
            from backend.core.printability import PrintabilityChecker
            checker = PrintabilityChecker()
            pr = checker.check(stats_dict)
            printability_result = pr.model_dump() if hasattr(pr, "model_dump") else pr
        except Exception as exc:
            warnings.append(f"Printability check failed: {exc}")

        await _dispatch_step("printability", "success", "Post-processing complete", 1.0)

        organic_result = {
            "model_url": model_url,
            "stl_url": stl_url,
            "threemf_url": threemf_url,
            "mesh_stats": stats_dict,
            "warnings": warnings,
            "printability": printability_result,
        }

        return {
            "model_url": model_url,
            "mesh_stats": stats_dict,
            "organic_warnings": warnings,
            "organic_result": organic_result,
            "printability": printability_result,
            "status": "post_processed",
        }

    except Exception as exc:
        reason = map_exception_to_failure_reason(exc)
        await _safe_update_job(job_id, status="failed", error=str(exc))
        await _safe_dispatch("job.failed", {
            "job_id": job_id, "error": str(exc),
            "failure_reason": reason, "status": "failed",
        })
        return {"error": str(exc), "failure_reason": reason, "status": "failed"}
