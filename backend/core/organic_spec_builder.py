"""OrganicSpec builder: translates user prompt via LLM and assembles OrganicSpec."""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from backend.models.organic import OrganicGenerateRequest, OrganicSpec

_SYSTEM_PROMPT = """You are a 3D model specification assistant. Given a user's description of a 3D object:
1. Translate the description to English (if not already English)
2. Identify the shape category (e.g., "figurine", "sports_equipment", "decorative", "mechanical_part", "art", "toy", "jewelry")
3. Suggest a bounding box [width_mm, depth_mm, height_mm] based on the real-world size of the object

Respond in JSON format:
{
  "prompt_en": "English description optimized for 3D generation",
  "shape_category": "category",
  "suggested_bounding_box": [width, depth, height] or null
}"""


class OrganicSpecBuilder:
    """Builds OrganicSpec from user request using LLM for prompt translation."""

    async def build(self, request: OrganicGenerateRequest) -> OrganicSpec:
        """Build an OrganicSpec from a user request."""
        llm_result = await self._call_llm(request.prompt)

        suggested_bbox = llm_result.get("suggested_bounding_box")
        if suggested_bbox is not None:
            suggested_bbox = tuple(suggested_bbox)

        user_bbox = request.constraints.bounding_box
        final_bbox = user_bbox if user_bbox is not None else suggested_bbox

        return OrganicSpec(
            prompt_en=llm_result["prompt_en"],
            prompt_original=request.prompt,
            shape_category=llm_result["shape_category"],
            suggested_bounding_box=suggested_bbox,
            final_bounding_box=final_bbox,
            engineering_cuts=list(request.constraints.engineering_cuts),
            quality_mode=request.quality_mode,
        )

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        """Call LLM to translate prompt and extract shape info.

        Override in tests with mock. In production, uses configured LLM.
        """
        try:
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
            response = await llm.ainvoke([
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ])
            return json.loads(response.content)
        except Exception as e:
            logger.warning("LLM call failed, using fallback: {}", e)
            return self._fallback(prompt)

    @staticmethod
    def _fallback(prompt: str) -> dict[str, Any]:
        """Fallback when LLM is unavailable: pass prompt as-is."""
        return {
            "prompt_en": prompt,
            "shape_category": "general",
            "suggested_bounding_box": None,
        }
