"""Tests for IntentParser — mock LLM, no real API calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.core.intent_parser import (
    PART_TYPE_MAPPING,
    IntentParser,
    ParsedIntent,
)
from backend.knowledge.part_types import PartType
from backend.models.intent import IntentSpec
from backend.models.template import ParamDefinition, ParametricTemplate


# ===================================================================
# Helpers — mock LLM callables
# ===================================================================


def _make_mock_llm(response: ParsedIntent):
    """Return an async callable that always returns *response*."""

    async def mock_llm(prompt: str, schema: Any) -> ParsedIntent:
        return response

    return mock_llm


def _make_failing_llm(error: Exception):
    """Return an async callable that raises *error*."""

    async def mock_llm(prompt: str, schema: Any) -> ParsedIntent:
        raise error

    return mock_llm


# ===================================================================
# Fixtures — minimal templates (no YAML I/O)
# ===================================================================


def _rotational_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="rotational_simple_disk",
        display_name="简单圆盘",
        part_type="rotational",
        params=[
            ParamDefinition(name="diameter", display_name="直径", unit="mm"),
            ParamDefinition(name="thickness", display_name="厚度", unit="mm"),
            ParamDefinition(
                name="bore_diameter", display_name="中心孔直径", unit="mm"
            ),
            ParamDefinition(name="chamfer", display_name="边缘倒角", unit="mm"),
        ],
    )


def _rotational_flange_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="rotational_flange_disk",
        display_name="法兰盘",
        part_type="rotational",
        params=[
            ParamDefinition(
                name="outer_diameter", display_name="外径", unit="mm"
            ),
            ParamDefinition(name="thickness", display_name="厚度", unit="mm"),
            ParamDefinition(
                name="bore_diameter", display_name="内径", unit="mm"
            ),
            ParamDefinition(name="pcd", display_name="螺栓圆直径", unit="mm"),
            ParamDefinition(
                name="hole_count", display_name="孔数", param_type="int"
            ),
            ParamDefinition(
                name="hole_diameter", display_name="孔径", unit="mm"
            ),
        ],
    )


def _plate_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="plate_rect",
        display_name="矩形板",
        part_type="plate",
        params=[
            ParamDefinition(name="length", display_name="长度", unit="mm"),
            ParamDefinition(name="width", display_name="宽度", unit="mm"),
            ParamDefinition(name="thickness", display_name="厚度", unit="mm"),
        ],
    )


def _gear_template() -> ParametricTemplate:
    return ParametricTemplate(
        name="gear_spur",
        display_name="直齿轮",
        part_type="gear",
        params=[
            ParamDefinition(
                name="module_val", display_name="模数", unit="mm"
            ),
            ParamDefinition(
                name="num_teeth", display_name="齿数", param_type="int"
            ),
            ParamDefinition(name="face_width", display_name="齿宽", unit="mm"),
            ParamDefinition(
                name="bore_diameter", display_name="中心孔直径", unit="mm"
            ),
        ],
    )


@pytest.fixture()
def templates() -> list[ParametricTemplate]:
    return [
        _rotational_template(),
        _rotational_flange_template(),
        _plate_template(),
        _gear_template(),
    ]


@pytest.fixture()
def parser(templates: list[ParametricTemplate], tmp_path: Path) -> IntentParser:
    """Parser with mock templates (no YAML loading)."""
    p = IntentParser.__new__(IntentParser)
    p._llm = None
    p._templates = templates
    return p


# ===================================================================
# ParsedIntent model
# ===================================================================


class TestParsedIntent:
    def test_create_default(self) -> None:
        pi = ParsedIntent()
        assert pi.part_category == ""
        assert pi.confidence == 0.0

    def test_create_full(self) -> None:
        pi = ParsedIntent(
            part_category="法兰盘",
            part_type_guess="法兰",
            extracted_params={"外径": 100},
            extracted_constraints=["需要M10螺栓"],
            confidence=0.85,
        )
        assert pi.part_category == "法兰盘"
        assert pi.extracted_params["外径"] == 100

    def test_json_round_trip(self) -> None:
        pi = ParsedIntent(
            part_category="轴",
            part_type_guess="阶梯轴",
            extracted_params={"长度": 200},
            confidence=0.9,
        )
        restored = ParsedIntent.model_validate_json(pi.model_dump_json())
        assert restored == pi


# ===================================================================
# _resolve_part_type — exact + fuzzy matching
# ===================================================================


class TestResolvePartType:
    def test_exact_chinese_flange(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("法兰") == PartType.ROTATIONAL

    def test_exact_chinese_shaft(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("阶梯轴") == PartType.ROTATIONAL_STEPPED

    def test_exact_chinese_plate(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("板件") == PartType.PLATE

    def test_exact_chinese_bracket(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("支架") == PartType.BRACKET

    def test_exact_chinese_housing(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("壳体") == PartType.HOUSING

    def test_exact_chinese_gear(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("齿轮") == PartType.GEAR

    def test_exact_english(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("rotational") == PartType.ROTATIONAL
        assert parser._resolve_part_type("plate") == PartType.PLATE
        assert parser._resolve_part_type("bracket") == PartType.BRACKET

    def test_substring_match(self, parser: IntentParser) -> None:
        # "法兰盘" contains "法兰"
        assert parser._resolve_part_type("法兰盘零件") == PartType.ROTATIONAL

    def test_case_insensitive(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("PLATE") == PartType.PLATE
        assert parser._resolve_part_type("Gear") == PartType.GEAR

    def test_with_whitespace(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("  法兰  ") == PartType.ROTATIONAL

    def test_unknown_returns_none(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("飞机") is None
        assert parser._resolve_part_type("xyz123") is None

    def test_empty_returns_none(self, parser: IntentParser) -> None:
        assert parser._resolve_part_type("") is None

    def test_all_mapping_entries_resolve(self, parser: IntentParser) -> None:
        for key, expected in PART_TYPE_MAPPING.items():
            result = parser._resolve_part_type(key)
            assert result == expected, f"Failed for key='{key}'"


# ===================================================================
# _identify_missing_params
# ===================================================================


class TestIdentifyMissingParams:
    def test_all_missing_for_rotational(self, parser: IntentParser) -> None:
        missing = parser._identify_missing_params(PartType.ROTATIONAL, {})
        # Union of rotational_simple_disk + rotational_flange_disk params
        assert "diameter" in missing
        assert "thickness" in missing
        assert "outer_diameter" in missing

    def test_some_provided(self, parser: IntentParser) -> None:
        missing = parser._identify_missing_params(
            PartType.ROTATIONAL,
            {"diameter": 100.0, "thickness": 20.0},
        )
        assert "diameter" not in missing
        assert "thickness" not in missing
        assert "bore_diameter" in missing

    def test_all_provided(self, parser: IntentParser) -> None:
        all_params = {
            "diameter": 100,
            "thickness": 20,
            "bore_diameter": 30,
            "chamfer": 2,
            "outer_diameter": 100,
            "pcd": 75,
            "hole_count": 4,
            "hole_diameter": 11,
        }
        missing = parser._identify_missing_params(
            PartType.ROTATIONAL, all_params
        )
        assert missing == []

    def test_display_name_mapping(self, parser: IntentParser) -> None:
        # User provides Chinese display_name as key
        missing = parser._identify_missing_params(
            PartType.PLATE,
            {"长度": 150.0},  # display_name for "length"
        )
        assert "length" not in missing

    def test_none_part_type(self, parser: IntentParser) -> None:
        missing = parser._identify_missing_params(None, {"width": 10.0})
        assert missing == []

    def test_gear_params(self, parser: IntentParser) -> None:
        missing = parser._identify_missing_params(
            PartType.GEAR,
            {"module_val": 2.0},
        )
        assert "num_teeth" in missing
        assert "face_width" in missing
        assert "bore_diameter" in missing
        assert "module_val" not in missing

    def test_result_is_sorted(self, parser: IntentParser) -> None:
        missing = parser._identify_missing_params(PartType.PLATE, {})
        assert missing == sorted(missing)


# ===================================================================
# parse() — end-to-end with mock LLM
# ===================================================================


class TestParseEndToEnd:
    @pytest.mark.asyncio
    async def test_parse_flange(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="法兰盘",
                part_type_guess="法兰",
                extracted_params={"outer_diameter": 100.0, "thickness": 16.0},
                extracted_constraints=["需要和M10螺栓配合"],
                confidence=0.85,
            )
        )
        result = await parser.parse("做一个法兰盘，外径100，厚16mm")
        assert isinstance(result, IntentSpec)
        assert result.part_type == PartType.ROTATIONAL
        assert result.known_params["outer_diameter"] == 100.0
        assert result.confidence == 0.85
        assert "需要和M10螺栓配合" in result.constraints
        assert "pcd" in result.missing_params

    @pytest.mark.asyncio
    async def test_parse_shaft(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="阶梯轴",
                part_type_guess="轴",
                extracted_params={"长度": 200.0},
                confidence=0.7,
            )
        )
        result = await parser.parse("做一个200mm长的阶梯轴")
        assert result.part_type == PartType.ROTATIONAL_STEPPED
        assert result.part_category == "阶梯轴"

    @pytest.mark.asyncio
    async def test_parse_plate(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="板件",
                part_type_guess="板",
                extracted_params={"length": 150.0, "width": 100.0},
                confidence=0.9,
            )
        )
        result = await parser.parse("做一个150×100的矩形板")
        assert result.part_type == PartType.PLATE
        assert result.known_params["length"] == 150.0
        assert "thickness" in result.missing_params

    @pytest.mark.asyncio
    async def test_parse_bracket(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="L型支架",
                part_type_guess="支架",
                extracted_params={"base_length": 100.0},
                confidence=0.8,
            )
        )
        result = await parser.parse("做一个L型支架")
        assert result.part_type == PartType.BRACKET

    @pytest.mark.asyncio
    async def test_parse_housing(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="圆筒壳体",
                part_type_guess="壳体",
                extracted_params={"outer_diameter": 100.0},
                confidence=0.75,
            )
        )
        result = await parser.parse("做一个圆筒壳体")
        assert result.part_type == PartType.HOUSING

    @pytest.mark.asyncio
    async def test_parse_gear(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="齿轮",
                part_type_guess="齿轮",
                extracted_params={"module_val": 2.0, "num_teeth": 24.0},
                confidence=0.95,
            )
        )
        result = await parser.parse("做一个模数2、24齿的齿轮")
        assert result.part_type == PartType.GEAR
        assert result.known_params["module_val"] == 2.0
        assert "face_width" in result.missing_params

    @pytest.mark.asyncio
    async def test_parse_general(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="管子",
                part_type_guess="通用",
                extracted_params={"length": 100.0},
                confidence=0.5,
            )
        )
        result = await parser.parse("做一个管子")
        assert result.part_type == PartType.GENERAL

    @pytest.mark.asyncio
    async def test_parse_with_image(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="法兰盘",
                part_type_guess="法兰",
                extracted_params={},
                confidence=0.6,
            )
        )
        result = await parser.parse("参考图片做法兰", image=b"fake_image")
        assert result.reference_image == "<uploaded>"

    @pytest.mark.asyncio
    async def test_parse_without_image(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="板",
                part_type_guess="板",
                confidence=0.5,
            )
        )
        result = await parser.parse("做一个板")
        assert result.reference_image is None

    @pytest.mark.asyncio
    async def test_parse_preserves_raw_text(self, parser: IntentParser) -> None:
        text = "做一个外径100mm的法兰盘"
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="法兰",
                part_type_guess="法兰",
                confidence=0.8,
            )
        )
        result = await parser.parse(text)
        assert result.raw_text == text


# ===================================================================
# parse() — edge cases
# ===================================================================


class TestParseEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_input(self, parser: IntentParser) -> None:
        result = await parser.parse("")
        assert result.confidence == 0.0
        assert result.part_type is None
        assert result.raw_text == ""

    @pytest.mark.asyncio
    async def test_whitespace_input(self, parser: IntentParser) -> None:
        result = await parser.parse("   ")
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_no_llm_raises(self, parser: IntentParser) -> None:
        parser._llm = None
        with pytest.raises(RuntimeError, match="llm_callable"):
            await parser.parse("做一个零件")

    @pytest.mark.asyncio
    async def test_unrecognized_part_type(
        self, parser: IntentParser
    ) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="飞船零件",
                part_type_guess="飞船",
                extracted_params={"size": 500.0},
                confidence=0.3,
            )
        )
        result = await parser.parse("做一个飞船零件")
        assert result.part_type is None
        assert result.missing_params == []

    @pytest.mark.asyncio
    async def test_confidence_clamped_high(
        self, parser: IntentParser
    ) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="板",
                part_type_guess="板",
                confidence=1.5,  # Out of range
            )
        )
        result = await parser.parse("做一个板")
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_confidence_clamped_low(
        self, parser: IntentParser
    ) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="板",
                part_type_guess="板",
                confidence=-0.5,  # Negative
            )
        )
        result = await parser.parse("做一个板")
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_llm_returns_empty_guess(
        self, parser: IntentParser
    ) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="未知零件",
                part_type_guess="",
                confidence=0.2,
            )
        )
        result = await parser.parse("做一个东西")
        assert result.part_type is None

    @pytest.mark.asyncio
    async def test_multiple_constraints(self, parser: IntentParser) -> None:
        parser._llm = _make_mock_llm(
            ParsedIntent(
                part_category="法兰",
                part_type_guess="法兰",
                extracted_constraints=[
                    "配合M10螺栓",
                    "耐压16MPa",
                    "材料304不锈钢",
                ],
                confidence=0.8,
            )
        )
        result = await parser.parse("法兰盘，M10螺栓，16MPa，304不锈钢")
        assert len(result.constraints) == 3


# ===================================================================
# _build_prompt
# ===================================================================


class TestBuildPrompt:
    def test_prompt_contains_user_input(self, parser: IntentParser) -> None:
        prompt = parser._build_prompt("做一个法兰盘", has_image=False)
        assert "做一个法兰盘" in prompt

    def test_prompt_mentions_image(self, parser: IntentParser) -> None:
        prompt = parser._build_prompt("参考图片", has_image=True)
        assert "图片" in prompt

    def test_prompt_no_image_mention(self, parser: IntentParser) -> None:
        prompt = parser._build_prompt("做板", has_image=False)
        assert "上传" not in prompt


# ===================================================================
# PART_TYPE_MAPPING completeness
# ===================================================================


class TestPartTypeMapping:
    def test_all_part_types_have_at_least_one_mapping(self) -> None:
        mapped_types = set(PART_TYPE_MAPPING.values())
        for pt in PartType:
            assert pt in mapped_types, f"PartType.{pt.name} has no mapping"

    def test_mapping_values_are_valid_part_types(self) -> None:
        for key, pt in PART_TYPE_MAPPING.items():
            assert isinstance(pt, PartType)
