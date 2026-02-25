from dataclasses import dataclass

from ..knowledge.part_types import DrawingSpec, PartType
from ..knowledge.modeling_strategies import get_strategy
from ..knowledge.examples import get_examples


@dataclass
class ModelingContext:
    """建模上下文 — 传递给 Code Generator 的全部信息"""
    drawing_spec: DrawingSpec
    strategy: str
    examples: list[tuple[str, str]]

    def to_prompt_text(self) -> str:
        """组装为 Coder 模型的完整输入 prompt"""
        parts = [
            self.drawing_spec.to_prompt_text(),
            "",
            self.strategy,
            "",
        ]
        if self.examples:
            parts.append("## 参考代码示例")
            parts.append("")
            for desc, code in self.examples:
                parts.append(f"### {desc}")
                parts.append(f"```python\n{code}\n```")
                parts.append("")
        return "\n".join(parts)


class ModelingStrategist:
    """阶段 1.5：根据零件类型选择建模策略（纯规则引擎，无 LLM）"""

    def select(self, spec: DrawingSpec) -> ModelingContext:
        strategy = get_strategy(spec.part_type)
        examples = get_examples(spec.part_type)
        return ModelingContext(
            drawing_spec=spec,
            strategy=strategy,
            examples=examples,
        )
