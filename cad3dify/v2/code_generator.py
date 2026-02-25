import re
from typing import Any, Union

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate, PromptTemplate

from ..chat_models import ChatModelParameters
from .modeling_strategist import ModelingContext


_CODE_GEN_PROMPT = """\
你是一位专业的 CAD 程序员，精通 Python cadquery 库。请根据下面的零件规格和建模策略，编写生成 3D CAD 模型的 Python 代码。

{modeling_context}

## 代码要求
1. 使用 cadquery 库（已安装，直接 import cadquery as cq）
2. 所有尺寸必须参数化（用变量，不要硬编码数字）
3. 严格遵循上面的建模策略（特别是基体构建方式和特征添加顺序）
4. 使用 `cq.exporters.export(result, "${{output_filename}}")` 导出 STEP 文件
5. 代码用 markdown 代码块包裹

## 关键原则
- 旋转体零件必须用 revolve profile 一次成型，不要用多个圆柱 union
- fillet 在 cut 之前
- 每个 fillet 操作用 try/except 包裹
- 螺栓孔用 for 循环 + math.cos/sin 计算位置

## 开始
请输出完整的 Python 代码：
"""


def _parse_code(input: dict) -> dict:
    """从 LLM 输出中提取 Python 代码"""
    match = re.search(r"```(?:python)?\n(.*?)\n```", input["text"], re.DOTALL)
    if match:
        return {"result": match.group(1).strip()}
    return {"result": None}


class CodeGeneratorChain(SequentialChain):
    """阶段2：Coder 模型根据 ModelingContext 生成 CadQuery 代码"""

    def __init__(self) -> None:
        prompt = ChatPromptTemplate(
            input_variables=["modeling_context"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=["modeling_context"],
                            template=_CODE_GEN_PROMPT,
                        ),
                    ]
                )
            ],
        )
        llm = ChatModelParameters.from_model_name("qwen-coder").create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result"],
                    transform=_parse_code,
                    atransform=None,
                ),
            ],
            input_variables=["modeling_context"],
            output_variables=["result"],
            verbose=True,
        )

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        if isinstance(inputs, ModelingContext):
            inputs = {"modeling_context": inputs.to_prompt_text()}
        elif "modeling_context" in inputs and isinstance(inputs["modeling_context"], ModelingContext):
            inputs["modeling_context"] = inputs["modeling_context"].to_prompt_text()
        return inputs
