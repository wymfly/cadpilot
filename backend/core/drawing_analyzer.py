import json
import re
import warnings
from typing import Any, Union

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.prompts.image import ImagePromptTemplate
from loguru import logger

from ..infra.image import ImageData
from ..knowledge.part_types import DrawingSpec, PartType

_DRAWING_ANALYSIS_PROMPT = """\
你是一位经验丰富的机械工程师，擅长阅读工程图纸。请仔细分析附带的 2D 工程图纸，提取所有几何信息。

## 分析步骤（必须严格按顺序执行）
请先在 ```reasoning``` 代码块中逐步分析，然后再输出 JSON：

1. **视图识别**：列出图纸包含的视图类型（正视图、俯视图、剖视图等）
2. **尺寸提取**：从每个视图中提取所有标注尺寸，注意区分直径和半径
3. **结构分析**：识别零件的层级结构（几层阶梯、每层的直径和高度）
4. **特征识别**：孔阵列（数量、直径、PCD）、圆角、倒角、键槽等
5. **零件分类**：根据上述分析判断零件类型
6. **建模方式**：确定最佳的 CadQuery 构建方法

分析完成后，输出 JSON。

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
{{
  "part_type": "rotational_stepped",
  "description": "零件的文字描述",
  "views": ["front_section", "top"],
  "overall_dimensions": {{"max_diameter": 100, "total_height": 30}},
  "base_body": {{
    "method": "revolve",
    "profile": [
      {{"diameter": 100, "height": 10, "label": "base_flange"}},
      {{"diameter": 40, "height": 10, "label": "middle_boss"}}
    ],
    "bore": {{"diameter": 10, "through": true}}
  }},
  "features": [
    {{"type": "hole_pattern", "pattern": "circular", "count": 6, "diameter": 10, "pcd": 70, "on_layer": "base_flange"}},
    {{"type": "fillet", "radius": 3, "locations": ["step_transitions"]}},
    {{"type": "chamfer", "size": 1, "locations": ["top_edge"]}}
  ],
  "notes": ["表面粗糙度 Ra 3.2"]
}}
```

## 重要提示
- 所有数值必须是数字，不要加单位
- diameter 是直径，不是半径
- 仔细区分剖视图中的虚线（隐藏线）和实线
- 如果某个尺寸无法确定，根据比例关系合理推测并在 notes 中说明
"""


def _parse_drawing_spec(input: dict) -> dict:
    """从 LLM 输出中提取 reasoning 和 JSON，解析为 DrawingSpec"""
    text = input["text"]

    # 提取 CoT reasoning（如果有）
    reasoning_match = re.search(r"```reasoning\s*\n(.*?)\n```", text, re.DOTALL)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else None
    if reasoning:
        logger.info(f"CoT reasoning ({len(reasoning)} chars):\n{reasoning}")

    # 提取 JSON — 优先直接匹配 ```json 块
    json_str = None
    json_match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # fallback: 匹配任意代码块中以 { 开头的内容
        for m in re.finditer(r"```(\w*)\s*\n(.*?)\n```", text, re.DOTALL):
            lang = m.group(1).lower()
            if lang in ("json", ""):
                candidate = m.group(2).strip()
                if candidate.startswith("{"):
                    json_str = candidate
                    break

    if json_str is None:
        # 最终回退：尝试从文本中提取裸 JSON 对象
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0).strip()
        else:
            json_str = text.strip()

    try:
        data = json.loads(json_str)
        # 验证 part_type 合法
        part_type = data.get("part_type", "general")
        if part_type not in [pt.value for pt in PartType]:
            data["part_type"] = "general"
        spec = DrawingSpec(**data)
        logger.info(f"Drawing analysis result: part_type={spec.part_type}, dims={spec.overall_dimensions}")
        return {"result": spec, "reasoning": reasoning}
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to parse DrawingSpec: {e}\nRaw text: {text}")
        return {"result": None, "reasoning": reasoning}


def fuse_ocr_with_spec(
    spec: DrawingSpec,
    image_bytes: bytes,
) -> DrawingSpec:
    """Fuse OCR dimension extraction with VL-generated DrawingSpec.

    Priority: OCR wins for numeric fields, VL wins for semantic fields.
    Returns the spec with ``overall_dimensions`` updated if OCR found dimensions.
    Gracefully returns original spec on any failure.
    """
    try:
        from backend.core.ocr_assist import OCRAssistant, merge_ocr_with_vl
        from backend.core.ocr_engine import get_ocr_fn
    except ImportError:
        return spec

    try:
        ocr_fn = get_ocr_fn()
        assistant = OCRAssistant(ocr_fn)
        ocr_annotations = assistant.extract_dimensions(image_bytes)
    except Exception:
        logger.warning("OCR extraction failed, using VL-only dimensions")
        return spec

    if not ocr_annotations:
        return spec

    ocr_dims_dict = _map_ocr_to_vl_keys(ocr_annotations, spec.overall_dimensions)
    if not ocr_dims_dict:
        return spec

    merged, _confidences = merge_ocr_with_vl(
        ocr_dims=ocr_dims_dict,
        vl_dims=spec.overall_dimensions,
    )
    spec.overall_dimensions = merged
    logger.info(f"OCR fusion: updated {len(ocr_dims_dict)} dimensions")
    return spec


def _map_ocr_to_vl_keys(
    annotations: list,
    vl_dims: dict[str, Any],
) -> dict[str, float]:
    """Map OCR DimensionAnnotation list to VL dimension key names by type heuristic.

    Pairs OCR annotations to VL keys by matching annotation type to key name
    patterns, then aligns by descending value (largest OCR value → largest VL key).
    """
    # Word-part sets: match against underscore-separated parts of key names.
    # E.g. "max_diameter" → parts ["max", "diameter"] → "diameter" matches.
    _DIAMETER_PARTS = {"diameter", "d", "od", "id"}
    _LINEAR_PARTS = {"height", "h", "length", "l", "width", "w", "thickness", "t", "depth"}

    def _matches(key: str, parts_set: set[str]) -> bool:
        return any(p in parts_set for p in key.lower().split("_"))

    def _numeric_val(v: Any) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0

    dia_keys = sorted(
        [k for k in vl_dims if _matches(k, _DIAMETER_PARTS)],
        key=lambda k: _numeric_val(vl_dims[k]), reverse=True,
    )
    lin_keys = sorted(
        [k for k in vl_dims if _matches(k, _LINEAR_PARTS)],
        key=lambda k: _numeric_val(vl_dims[k]), reverse=True,
    )

    dia_annots = sorted(
        [a for a in annotations if a.type == "diameter"],
        key=lambda a: a.value, reverse=True,
    )
    lin_annots = sorted(
        [a for a in annotations if a.type == "linear"],
        key=lambda a: a.value, reverse=True,
    )

    result: dict[str, float] = {}
    for i, key in enumerate(dia_keys):
        if i < len(dia_annots):
            result[key] = dia_annots[i].value
    for i, key in enumerate(lin_keys):
        if i < len(lin_annots):
            result[key] = lin_annots[i].value
    return result


class DrawingAnalyzerChain(SequentialChain):
    """阶段1：VL 模型分析工程图纸，输出结构化 DrawingSpec"""

    def __init__(self) -> None:
        warnings.warn(
            "DrawingAnalyzerChain is deprecated. Use build_vision_analysis_chain() from backend.graph.chains.",
            DeprecationWarning,
            stacklevel=2,
        )
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
        from ..infra.llm_config_manager import get_model_for_role

        llm = get_model_for_role("vision_analyzer").create_chat_model()

        super().__init__(
            chains=[
                LLMChain(prompt=prompt, llm=llm),
                TransformChain(
                    input_variables=["text"],
                    output_variables=["result", "reasoning"],
                    transform=_parse_drawing_spec,
                    atransform=None,
                ),
            ],
            input_variables=["image_type", "image_data"],
            output_variables=["result", "reasoning"],
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
