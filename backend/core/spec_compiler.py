"""SpecCompiler — unified code compilation dispatch.

Encapsulates the template-first-then-LLM-fallback strategy:
1. Try TemplateEngine.render() + SafeExecutor if matched_template is set
2. Fall back to V2 pipeline CodeGeneratorChain if template path fails or is unavailable
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CompilationError(Exception):
    """Raised when both template and LLM paths fail."""


@dataclass
class CompileResult:
    """Result of a SpecCompiler.compile() call."""

    method: str  # "template" | "llm_fallback"
    step_path: str = ""
    template_name: str | None = None
    cadquery_code: str = ""
    errors: list[str] = field(default_factory=list)


class SpecCompiler:
    """Stateless dispatcher: template-first, LLM-fallback.

    Usage::

        compiler = SpecCompiler()
        result = compiler.compile(
            matched_template="cylinder_simple",
            params={"diameter": 50, "height": 100},
            output_path="/tmp/model.step",
        )
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._templates_dir = templates_dir or (
            Path(__file__).parent.parent / "knowledge" / "templates"
        )

    def compile(
        self,
        *,
        matched_template: str | None,
        params: dict[str, Any],
        output_path: str,
        input_text: str = "",
        intent: dict | None = None,
    ) -> CompileResult:
        """Compile params into a STEP file.

        Strategy:
        1. If matched_template is set -> render + execute
        2. Else -> LLM fallback via V2 pipeline
        """
        if matched_template:
            try:
                return self._compile_from_template(matched_template, params, output_path)
            except Exception as exc:
                logger.warning(
                    "Template compilation failed (%s), trying LLM fallback", exc
                )

        # LLM fallback
        try:
            return self._compile_from_llm(params, output_path, input_text, intent)
        except Exception as llm_exc:
            raise CompilationError(
                f"Both template and LLM paths failed. "
                f"Template: {matched_template!r}, LLM error: {llm_exc}"
            ) from llm_exc

    def _compile_from_template(
        self, template_name: str, params: dict, output_path: str
    ) -> CompileResult:
        """Render template + execute in sandbox."""
        from backend.core.template_engine import TemplateEngine
        from backend.infra.sandbox import SafeExecutor

        engine = TemplateEngine.from_directory(self._templates_dir)
        code = engine.render(template_name, params, output_filename=output_path)

        executor = SafeExecutor(timeout_s=120)
        result = executor.execute(code)
        if not result.success:
            raise RuntimeError(f"Sandbox execution failed: {result.stderr}")
        if not Path(output_path).exists():
            raise RuntimeError(f"STEP file not created at {output_path}")

        return CompileResult(
            method="template",
            template_name=template_name,
            step_path=output_path,
            cadquery_code=code,
        )

    def _compile_from_llm(
        self, params: dict, output_path: str, input_text: str, intent: dict | None
    ) -> CompileResult:
        """Fall back to V2 pipeline CodeGeneratorChain."""
        from backend.pipeline.pipeline import generate_step_from_2d_cad_image

        # Build description from intent or params
        description = input_text
        if not description and intent:
            description = intent.get("raw_text", str(params))

        # Use V2 pipeline for LLM-based generation
        generate_step_from_2d_cad_image(
            image_filepath="",  # no image for text path
            output_filepath=output_path,
        )

        if not Path(output_path).exists():
            raise RuntimeError(
                f"LLM generation failed: STEP file not created at {output_path}"
            )

        return CompileResult(
            method="llm_fallback",
            step_path=output_path,
        )


def rank_templates(
    candidates: list,
    known_params: dict[str, Any],
) -> list:
    """Rank template candidates by parameter coverage.

    Coverage = len(known ∩ template_params) / len(template_params).
    Ties broken by fewer total params (simpler template preferred).
    """
    if not candidates:
        return []

    def _score(tpl) -> tuple[float, int]:
        param_names = {p.name for p in tpl.params}
        overlap = len(param_names & set(known_params.keys()))
        coverage = overlap / len(param_names) if param_names else 0.0
        return (-coverage, len(param_names))  # negative for descending sort

    return sorted(candidates, key=_score)
