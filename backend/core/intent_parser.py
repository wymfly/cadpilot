"""IntentParser — LLM-driven natural-language intent parser.

Parses free-form user input (optionally with an image) into an
``IntentSpec`` that captures part category, type, extracted parameters,
missing parameters, constraints and confidence.

In tests, inject a mock ``llm_callable`` to avoid real API calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from pydantic import BaseModel

from backend.knowledge.part_types import PartType
from backend.models.intent import IntentSpec
from backend.models.template import ParametricTemplate, load_all_templates


# ---------------------------------------------------------------------------
# LLM output schema (intermediate)
# ---------------------------------------------------------------------------


class ParsedIntent(BaseModel):
    """Structured intent returned by the LLM (intermediate format)."""

    part_category: str = ""
    part_type_guess: str = ""
    extracted_params: dict[str, float] = {}
    extracted_constraints: list[str] = []
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Part-type mapping (Chinese → PartType)
# ---------------------------------------------------------------------------

PART_TYPE_MAPPING: dict[str, PartType] = {
    # rotational
    "法兰": PartType.ROTATIONAL,
    "法兰盘": PartType.ROTATIONAL,
    "圆盘": PartType.ROTATIONAL,
    "圆柱": PartType.ROTATIONAL,
    "盘": PartType.ROTATIONAL,
    "rotational": PartType.ROTATIONAL,
    # rotational_stepped
    "轴": PartType.ROTATIONAL_STEPPED,
    "阶梯轴": PartType.ROTATIONAL_STEPPED,
    "传动轴": PartType.ROTATIONAL_STEPPED,
    "stepped_shaft": PartType.ROTATIONAL_STEPPED,
    "rotational_stepped": PartType.ROTATIONAL_STEPPED,
    # plate
    "板": PartType.PLATE,
    "板件": PartType.PLATE,
    "平板": PartType.PLATE,
    "底板": PartType.PLATE,
    "plate": PartType.PLATE,
    # bracket
    "支架": PartType.BRACKET,
    "L型": PartType.BRACKET,
    "L型支架": PartType.BRACKET,
    "U型": PartType.BRACKET,
    "U型支架": PartType.BRACKET,
    "角码": PartType.BRACKET,
    "bracket": PartType.BRACKET,
    # housing
    "壳体": PartType.HOUSING,
    "箱体": PartType.HOUSING,
    "外壳": PartType.HOUSING,
    "housing": PartType.HOUSING,
    # gear
    "齿轮": PartType.GEAR,
    "直齿轮": PartType.GEAR,
    "gear": PartType.GEAR,
    # general
    "通用": PartType.GENERAL,
    "general": PartType.GENERAL,
}


# ---------------------------------------------------------------------------
# Default templates directory
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent.parent / "knowledge" / "templates"

# Type alias for the async LLM callable
LLMCallable = Callable[
    [str, type[BaseModel]],
    Coroutine[Any, Any, ParsedIntent],
]


# ---------------------------------------------------------------------------
# IntentParser
# ---------------------------------------------------------------------------


class IntentParser:
    """LLM-driven intent parser — understands, does not compute.

    Parameters
    ----------
    llm_callable:
        An async callable ``(prompt: str, schema: type) -> ParsedIntent``.
        In production this wraps the real LLM; in tests a mock is injected.
    templates_dir:
        Directory of parametric YAML templates, used to identify missing
        parameters.  Defaults to ``backend/knowledge/templates/``.
    """

    def __init__(
        self,
        llm_callable: Optional[LLMCallable] = None,
        templates_dir: Optional[Path] = None,
    ) -> None:
        self._llm = llm_callable
        self._templates: list[ParametricTemplate] = []
        tdir = templates_dir or _TEMPLATES_DIR
        if tdir.exists():
            self._templates = load_all_templates(tdir)

    # -- public API ----------------------------------------------------------

    async def parse(
        self,
        user_input: str,
        image: Optional[bytes] = None,
    ) -> IntentSpec:
        """Parse natural-language input into an ``IntentSpec``.

        Steps:
        1. Call LLM with structured output → ``ParsedIntent``
        2. Resolve ``part_type_guess`` to a ``PartType``
        3. Identify missing parameters from template definitions
        4. Assemble ``IntentSpec``
        """
        if not user_input.strip():
            return IntentSpec(raw_text=user_input, confidence=0.0)

        if self._llm is None:
            raise RuntimeError(
                "IntentParser requires an llm_callable; none was provided."
            )

        prompt = self._build_prompt(user_input, has_image=image is not None)
        parsed: ParsedIntent = await self._llm(prompt, ParsedIntent)

        part_type = self._resolve_part_type(parsed.part_type_guess)
        missing = self._identify_missing_params(
            part_type, parsed.extracted_params
        )

        confidence = min(max(parsed.confidence, 0.0), 1.0)

        return IntentSpec(
            part_category=parsed.part_category,
            part_type=part_type,
            known_params=parsed.extracted_params,
            missing_params=missing,
            constraints=parsed.extracted_constraints,
            reference_image=None if image is None else "<uploaded>",
            confidence=confidence,
            raw_text=user_input,
        )

    # -- internal helpers ----------------------------------------------------

    def _build_prompt(self, user_input: str, *, has_image: bool) -> str:
        """Build the LLM prompt from user input."""
        parts = [
            "你是一个 CAD 零件意图解析器。分析用户输入，提取零件类别、类型、参数和约束。",
            "",
            f"用户输入: {user_input}",
        ]
        if has_image:
            parts.append("（用户还上传了参考图片）")
        parts.append("")
        parts.append("请提取以下信息:")
        parts.append("- part_category: 零件类别（中文）")
        parts.append(
            "- part_type_guess: 零件类型猜测（法兰/轴/板/支架/壳体/齿轮/通用）"
        )
        parts.append("- extracted_params: 数值参数（名称→数值）")
        parts.append("- extracted_constraints: 约束条件列表")
        parts.append("- confidence: 0-1 置信度")
        return "\n".join(parts)

    def _resolve_part_type(self, guess: str) -> Optional[PartType]:
        """Fuzzy-match a part-type guess to a ``PartType`` enum.

        Tries exact match first, then substring containment.
        Both guess and mapping keys are lowercased for comparison.
        """
        if not guess:
            return None

        normalized = guess.strip().lower()

        # Build a lowercased mapping for case-insensitive lookup
        lower_mapping: dict[str, PartType] = {
            k.lower(): v for k, v in PART_TYPE_MAPPING.items()
        }

        # Exact match
        if normalized in lower_mapping:
            return lower_mapping[normalized]

        # Substring containment: check if any key is contained in guess
        for key, pt in lower_mapping.items():
            if key in normalized:
                return pt

        # Reverse: check if guess is contained in any key
        for key, pt in lower_mapping.items():
            if normalized in key:
                return pt

        return None

    def _identify_missing_params(
        self,
        part_type: Optional[PartType],
        known_params: dict[str, float],
    ) -> list[str]:
        """Identify parameters required by templates but not in *known_params*.

        Collects the union of all parameter names from templates matching
        the given ``part_type``, then subtracts the keys already provided.
        """
        if part_type is None:
            return []

        required: set[str] = set()
        for tmpl in self._templates:
            if tmpl.part_type == part_type.value:
                for p in tmpl.params:
                    required.add(p.name)

        known_keys = set(known_params.keys())

        # Also consider display_name → name mapping
        display_to_name: dict[str, str] = {}
        for tmpl in self._templates:
            if tmpl.part_type == part_type.value:
                for p in tmpl.params:
                    display_to_name[p.display_name] = p.name

        for k in known_params:
            if k in display_to_name:
                known_keys.add(display_to_name[k])

        return sorted(required - known_keys)
