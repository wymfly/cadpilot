from .rotational import ROTATIONAL_EXAMPLES
from .plate import PLATE_EXAMPLES
from .bracket import BRACKET_EXAMPLES
from .housing import HOUSING_EXAMPLES

from ..part_types import PartType

EXAMPLES_BY_TYPE: dict[PartType, list[tuple[str, str]]] = {
    PartType.ROTATIONAL: ROTATIONAL_EXAMPLES,
    PartType.ROTATIONAL_STEPPED: ROTATIONAL_EXAMPLES,  # 共享旋转体示例
    PartType.PLATE: PLATE_EXAMPLES,
    PartType.BRACKET: BRACKET_EXAMPLES,
    PartType.HOUSING: HOUSING_EXAMPLES,
}


def get_examples(part_type: PartType) -> list[tuple[str, str]]:
    """获取零件类型对应的 few-shot 示例列表，每项为 (说明, 代码)"""
    return EXAMPLES_BY_TYPE.get(part_type, [])
