"""Tests for OrganicSpecBuilder with mocked LLM responses."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.models.organic import (
    FlatBottomCut,
    HoleCut,
    OrganicConstraints,
    OrganicGenerateRequest,
    OrganicSpec,
)


def _mock_llm_result(
    prompt_en: str = "golf club head",
    shape_category: str = "sports_equipment",
    suggested_bounding_box: tuple[float, float, float] | None = (80, 80, 60),
) -> dict:
    return {
        "prompt_en": prompt_en,
        "shape_category": shape_category,
        "suggested_bounding_box": suggested_bounding_box,
    }


class TestOrganicSpecBuilder:
    async def test_chinese_prompt_translated(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(prompt="高尔夫球头")

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result()
            spec = await builder.build(request)

        assert spec.prompt_en == "golf club head"
        assert spec.prompt_original == "高尔夫球头"
        assert isinstance(spec, OrganicSpec)

    async def test_shape_category_extracted(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(prompt="动漫手办")

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result(
                prompt_en="anime figurine",
                shape_category="figurine",
            )
            spec = await builder.build(request)

        assert spec.shape_category == "figurine"

    async def test_bounding_box_suggestion(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(prompt="花瓶")

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result(
                prompt_en="vase",
                shape_category="decorative",
                suggested_bounding_box=(100, 100, 200),
            )
            spec = await builder.build(request)

        assert spec.suggested_bounding_box == (100, 100, 200)
        # Without user-provided bbox, final = suggested
        assert spec.final_bounding_box == (100, 100, 200)

    async def test_user_bbox_overrides_suggestion(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(
            prompt="花瓶",
            constraints=OrganicConstraints(bounding_box=(50, 50, 100)),
        )

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result(
                prompt_en="vase",
                shape_category="decorative",
                suggested_bounding_box=(100, 100, 200),
            )
            spec = await builder.build(request)

        assert spec.suggested_bounding_box == (100, 100, 200)
        assert spec.final_bounding_box == (50, 50, 100)  # user override

    async def test_engineering_cuts_pass_through(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        cuts = [
            FlatBottomCut(),
            HoleCut(diameter=10.0, depth=25.0),
        ]
        request = OrganicGenerateRequest(
            prompt="高尔夫球头",
            constraints=OrganicConstraints(engineering_cuts=cuts),
        )

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result()
            spec = await builder.build(request)

        assert len(spec.engineering_cuts) == 2
        assert spec.engineering_cuts[0].type == "flat_bottom"
        assert spec.engineering_cuts[1].type == "hole"

    async def test_quality_mode_pass_through(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(prompt="球头", quality_mode="high")

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result()
            spec = await builder.build(request)

        assert spec.quality_mode == "high"

    async def test_no_suggested_bbox(self) -> None:
        from backend.core.organic_spec_builder import OrganicSpecBuilder

        builder = OrganicSpecBuilder()
        request = OrganicGenerateRequest(prompt="抽象雕塑")

        with patch.object(
            builder, "_call_llm", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = _mock_llm_result(
                prompt_en="abstract sculpture",
                shape_category="art",
                suggested_bounding_box=None,
            )
            spec = await builder.build(request)

        assert spec.suggested_bounding_box is None
        assert spec.final_bounding_box is None
