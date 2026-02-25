"""Few-shot example library with feature-tagged examples for intelligent retrieval."""

from __future__ import annotations

from ._base import TaggedExample
from .rotational import ROTATIONAL_EXAMPLES
from .plate import PLATE_EXAMPLES
from .bracket import BRACKET_EXAMPLES
from .housing import HOUSING_EXAMPLES
from .gear import GEAR_EXAMPLES
from .general import GENERAL_EXAMPLES

from ..part_types import PartType

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EXAMPLES_BY_TYPE: dict[PartType, list[TaggedExample]] = {
    PartType.ROTATIONAL: ROTATIONAL_EXAMPLES,
    PartType.ROTATIONAL_STEPPED: ROTATIONAL_EXAMPLES,  # 共享旋转体示例
    PartType.PLATE: PLATE_EXAMPLES,
    PartType.BRACKET: BRACKET_EXAMPLES,
    PartType.HOUSING: HOUSING_EXAMPLES,
    PartType.GEAR: GEAR_EXAMPLES,
    PartType.GENERAL: GENERAL_EXAMPLES,
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_examples(part_type: PartType) -> list[tuple[str, str]]:
    """获取零件类型对应的 few-shot 示例列表，每项为 (说明, 代码)。

    向后兼容的接口，供旧版 prompt builder 使用。
    """
    return [
        (ex.description, ex.code)
        for ex in EXAMPLES_BY_TYPE.get(part_type, [])
    ]


def get_tagged_examples(part_type: PartType) -> list[TaggedExample]:
    """获取带特征标签的示例列表，供特征匹配选择器使用。"""
    return EXAMPLES_BY_TYPE.get(part_type, [])


__all__ = [
    "TaggedExample",
    "EXAMPLES_BY_TYPE",
    "get_examples",
    "get_tagged_examples",
]
