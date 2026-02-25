import json
import re
from typing import Any, Union

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.prompts.image import ImagePromptTemplate
from loguru import logger

from ..chat_models import ChatModelParameters
from ..image import ImageData
from ..knowledge.part_types import DrawingSpec, PartType

_DRAWING_ANALYSIS_PROMPT = """\
你是一位经验丰富的机械工程师，擅长阅读工程图纸。请仔细分析附带的 2D 工程图纸，提取所有几何信息。

## 任务
1. 识别零件类型（从以下选项中选择）：
   - rotational: 旋转体（圆柱、圆锥）
   - rotational_stepped: 阶梯旋转体（法兰盘、阶梯轴）
   - plate: 板件
   - bracket: 支架/角件
   - housing: 箱体/壳体
   - gear: 齿轮
   - general: 其他

2. 识别图纸中包含的视图（front, top, side, section, isometric）

3. 提取所有标注尺寸，包括：
   - 直径（φ）、半径（R）、长度、宽度、高度
   - 孔的数量、直径、分布（PCD）
   - 圆角（R）、倒角（C）
   - 公差（如有）

4. 确定基体构建方式：
   - revolve: 旋转体零件（首选！阶梯轴、法兰盘等）
   - extrude: 板件、型材
   - loft: 变截面体
   - shell: 箱体（先实体后抽壳）

## 输出格式
严格输出以下 JSON 格式，不要输出其他内容：

```json
{
  "part_type": "rotational_stepped",
  "description": "零件的文字描述",
  "views": ["front_section", "top"],
  "overall_dimensions": {"max_diameter": 100, "total_height": 30},
  "base_body": {
    "method": "revolve",
    "profile": [
      {"diameter": 100, "height": 10, "label": "base_flange"},
      {"diameter": 40, "height": 10, "label": "middle_boss"}
    ],
    "bore": {"diameter": 10, "through": true}
  },
  "features": [
    {"type": "hole_pattern", "pattern": "circular", "count": 6, "diameter": 10, "pcd": 70, "on_layer": "base_flange"},
    {"type": "fillet", "radius": 3, "locations": ["step_transitions"]},
    {"type": "chamfer", "size": 1, "locations": ["top_edge"]}
  ],
  "notes": ["表面粗糙度 Ra 3.2"]
}
```

## 重要提示
- 所有数值必须是数字，不要加单位
- diameter 是直径，不是半径
- 仔细区分剖视图中的虚线（隐藏线）和实线
- 如果某个尺寸无法确定，根据比例关系合理推测并在 notes 中说明
"""


def _parse_drawing_spec(input: dict) -> dict:
    """从 LLM 输出中提取 JSON 并解析为 DrawingSpec"""
    text = input["text"]
    # 尝试从 markdown 代码块中提取 JSON
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        # 尝试直接解析整个文本
        json_str = text.strip()

    try:
        data = json.loads(json_str)
        # 验证 part_type 合法
        part_type = data.get("part_type", "general")
        if part_type not in [pt.value for pt in PartType]:
            data["part_type"] = "general"
        spec = DrawingSpec(**data)
        logger.info(f"Drawing analysis result: part_type={spec.part_type}, dims={spec.overall_dimensions}")
        return {"result": spec}
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse DrawingSpec: {e}\nRaw text: {text}")
        return {"result": None}


class DrawingAnalyzerChain(SequentialChain):
    """阶段1：VL 模型分析工程图纸，输出结构化 DrawingSpec"""

    def __init__(self) -> None:
        prompt = ChatPromptTemplate(
            input_variables=["image_type", "image_data"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=[],
                            template=_DRAWING_ANALYSIS_PROMPT,
                        ),
                        ImagePromptTemplate(
                            input_variables=["image_type", "image_data"],
                            template={
                                "url": "data:image/{image_type};base64,{image_data}",
                            },
                        ),
                    ]
                )
            ],
        )
        llm = ChatModelParameters.from_model_name("qwen-vl").create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result"],
                    transform=_parse_drawing_spec,
                    atransform=None,
                ),
            ],
            input_variables=["image_type", "image_data"],
            output_variables=["result"],
            verbose=True,
        )

    def prep_inputs(self, inputs: Union[dict[str, Any], Any]) -> dict[str, str]:
        if isinstance(inputs, ImageData):
            inputs = {"input": inputs}
        elif "input" not in inputs:
            raise ValueError("inputs must be ImageData or dict with 'input' key")
        image = inputs["input"]
        assert isinstance(image, ImageData)
        inputs["image_type"] = image.type
        inputs["image_data"] = image.data
        return inputs
