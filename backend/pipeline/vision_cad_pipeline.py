"""Pipeline helper functions extracted from backend.api.generate.

These wrappers are used by LangGraph graph nodes and are kept at module
level for mockability in tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# STEP -> GLB conversion
# ---------------------------------------------------------------------------


def _convert_step_to_glb(step_path: str, glb_path: str) -> None:
    """Convert STEP to GLB for preview. Wrapper for mockability."""
    from backend.core.format_exporter import FormatExporter

    exporter = FormatExporter()
    glb_bytes = exporter.to_gltf_for_preview(step_path)
    with open(glb_path, "wb") as f:
        f.write(glb_bytes)


# ---------------------------------------------------------------------------
# Template matching
# ---------------------------------------------------------------------------


def _match_template(
    text: str,
) -> tuple[Any, list[Any]]:
    """Simple keyword matching to find a parametric template.

    Returns ``(template, params)`` where *params* is
    ``list[ParamDefinition]``.  If nothing matches, returns
    ``(None, [])``.
    """
    try:
        from backend.core.template_engine import TemplateEngine

        _templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)
        templates = engine.list_templates()
    except Exception as exc:
        logger.warning("Template engine initialization failed: %s", exc)
        return None, []

    text_lower = text.lower()
    for tpl in templates:
        # Match by display_name (Chinese) or name (machine-readable)
        if tpl.display_name in text or tpl.name in text_lower:
            return tpl, tpl.params

    # No match — return None with empty params
    return None, []


# ---------------------------------------------------------------------------
# Template-based generation
# ---------------------------------------------------------------------------


def _run_template_generation(
    job: Any, confirmed_params: dict[str, float], step_path: str
) -> bool:
    """Use parametric template to generate STEP file.  Returns *True* on success."""
    template_name: str | None = None
    if job.result and isinstance(job.result, dict):
        template_name = job.result.get("template_name")

    if not template_name:
        return False

    try:
        from backend.core.template_engine import TemplateEngine

        _templates_dir = Path(__file__).parent.parent / "knowledge" / "templates"
        engine = TemplateEngine.from_directory(_templates_dir)
        template = engine.get_template(template_name)  # noqa: F841 — validates existence
    except Exception as exc:
        logger.warning("Template load failed for '%s': %s", template_name, exc)
        return False

    # Render Jinja2 template with confirmed params
    try:
        code = engine.render(
            template_name,
            confirmed_params,
            output_filename=step_path,
        )
    except Exception as exc:
        logger.warning("Template render failed for '%s': %s", template_name, exc)
        return False

    # Execute in sandbox
    try:
        from backend.infra.sandbox import SafeExecutor

        executor = SafeExecutor(timeout_s=120)
        result = executor.execute(code)
        return result.success and Path(step_path).exists()
    except Exception as exc:
        logger.warning("Sandbox execution failed for '%s': %s", template_name, exc)
        return False


# ---------------------------------------------------------------------------
# Printability check
# ---------------------------------------------------------------------------


def _run_printability_check(step_path: str) -> dict[str, Any] | None:
    """Run printability check on a STEP file. Returns None on failure."""
    try:
        from backend.core.geometry_extractor import extract_geometry_from_step
        from backend.core.printability import PrintabilityChecker

        geometry_info = extract_geometry_from_step(step_path)
        checker = PrintabilityChecker()
        result = checker.check(geometry_info)
        mat = checker.estimate_material(geometry_info)
        time_est = checker.estimate_print_time(geometry_info)
        data = result.model_dump()
        data["material_estimate"] = {
            "filament_weight_g": mat.filament_weight_g,
            "filament_length_m": mat.filament_length_m,
            "cost_estimate_cny": mat.cost_estimate_cny,
        }
        data["time_estimate"] = {
            "total_minutes": time_est.total_minutes,
            "layer_count": time_est.layer_count,
        }
        return data
    except Exception as exc:
        logger.warning("Printability check failed for %s: %s", step_path, exc)
        return None
