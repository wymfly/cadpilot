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
from ..knowledge.part_types import DrawingSpec
from .validators import (
    _get_bbox_from_step,
    validate_bounding_box,
    validate_code_params,
)

# ---- 阶段 4a: VL 模型分析差异 ----

_COMPARE_PROMPT = """\
你是一位经验丰富的机械工程师。请对比以下两张图片：
1. 第一张是原始的 2D 工程图纸
2. 第二张是根据代码生成的 3D 模型渲染图

## 预期规格（来自图纸分析）
{drawing_spec}

## 当前代码
```python
{code}
```

## 任务
请仔细对比渲染结果与原始图纸，找出所有不一致的地方。对每个问题，给出：
1. 问题描述（什么地方不对）
2. 预期值（图纸上的尺寸）
3. 修改建议（需要怎么改代码）

输出格式：
```
问题1: [描述]
预期: [值]
修改: [建议]

问题2: [描述]
预期: [值]
修改: [建议]
```

如果渲染结果与图纸完全一致，输出 "PASS"。

## 判断标准（严格遵守）
- 如果所有尺寸在 5% 误差范围内，且结构正确（阶梯数、孔数一致），输出 "PASS"
- 只报告**明确的结构性差异**，如：缺少阶梯层、孔数不对、整体形状错误
- 不要报告：渲染角度差异、光照/阴影效果、微小的圆角差异、表面纹理
- 不确定的问题不要报告，宁可漏报不可误报
"""

# ---- 阶段 4b: Coder 模型修改代码 ----

_FIX_CODE_PROMPT = """\
你是一位 CAD 程序员。以下代码生成的 3D 模型与预期不符，请根据修改指令修正代码。

## 当前代码
```python
{code}
```

## 修改指令
{fix_instructions}

## 要求
1. 只修改必要的部分，保持代码结构不变
2. 确保所有尺寸参数化
3. 保留 export 语句
4. 代码用 markdown 代码块包裹

## 绝对禁止（违反则代码无效）
1. 不要引入代码中未使用的新 API（如 addAnnotation、addText、show_object）
2. 不要修改 export 语句
3. 不要添加可视化/渲染/标注代码
4. 不要删除已有的 try/except 安全包裹
5. 只修改数值参数和几何操作，不要重构代码结构
6. 修改后的代码必须能独立运行并导出 STEP 文件

请输出修正后的完整代码：
"""


def _parse_code(input: dict) -> dict:
    match = re.search(r"```(?:python)?\n(.*?)\n```", input["text"], re.DOTALL)
    if match:
        return {"result": match.group(1).strip()}
    return {"result": None}


def _extract_comparison(input: dict) -> dict:
    """提取对比结果"""
    text = input["text"]
    if "PASS" in text.upper() and len(text.strip()) < 20:
        return {"result": None}  # 完全匹配，无需修改
    return {"result": text}


class SmartCompareChain(SequentialChain):
    """阶段 4a: VL 模型对比原图和渲染图"""

    def __init__(self) -> None:
        prompt = ChatPromptTemplate(
            input_variables=[
                "drawing_spec", "code",
                "original_image_type", "original_image_data",
                "rendered_image_type", "rendered_image_data",
            ],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=["drawing_spec", "code"],
                            template=_COMPARE_PROMPT,
                        ),
                        ImagePromptTemplate(
                            input_variables=["original_image_type", "original_image_data"],
                            template={"url": "data:image/{original_image_type};base64,{original_image_data}"},
                        ),
                        ImagePromptTemplate(
                            input_variables=["rendered_image_type", "rendered_image_data"],
                            template={"url": "data:image/{rendered_image_type};base64,{rendered_image_data}"},
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
                    transform=_extract_comparison,
                    atransform=None,
                ),
            ],
            input_variables=[
                "drawing_spec", "code",
                "original_image_type", "original_image_data",
                "rendered_image_type", "rendered_image_data",
            ],
            output_variables=["result"],
            verbose=True,
        )


class SmartFixChain(SequentialChain):
    """阶段 4b: Coder 模型根据修改指令修正代码"""

    def __init__(self) -> None:
        prompt = ChatPromptTemplate(
            input_variables=["code", "fix_instructions"],
            messages=[
                HumanMessagePromptTemplate(
                    prompt=[
                        PromptTemplate(
                            input_variables=["code", "fix_instructions"],
                            template=_FIX_CODE_PROMPT,
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
            input_variables=["code", "fix_instructions"],
            output_variables=["result"],
            verbose=True,
        )


class SmartRefiner:
    """增强版改进器：三层防线（静态校验 → 包围盒 → VL 对比）+ Coder 修正"""

    def __init__(self):
        self.compare_chain = SmartCompareChain()
        self.fix_chain = SmartFixChain()

    def refine(
        self,
        code: str,
        original_image: ImageData,
        rendered_image: ImageData,
        drawing_spec: DrawingSpec,
        step_filepath: str | None = None,
    ) -> str | None:
        """
        零风险改进流程：Layer 1/2 仅用于诊断上下文，VL 始终运行（质量唯一裁判）。

        Layer 1（静态参数校验）和 Layer 2（包围盒校验）收集诊断信息并注入
        Coder 修复指令，但不跳过 VL 调用。VL 是决定是否需要修复的唯一依据。

        返回修正后的代码，如果 VL 判定 PASS 则返回 None。
        """
        static_notes: list[str] = []

        # ---- Layer 1: 静态参数校验（诊断，不影响 VL 执行） ----
        param_result = validate_code_params(code, drawing_spec)
        if not param_result.passed:
            logger.warning(
                f"Smart refiner Layer 1: static validation — "
                f"{len(param_result.mismatches)} mismatches (VL will still run)"
            )
            for m in param_result.mismatches:
                logger.warning(f"  - {m}")
            static_notes.extend(param_result.mismatches)
        else:
            logger.info("Smart refiner Layer 1: static validation PASSED")

        # ---- Layer 2: 包围盒校验（诊断，不影响 VL 执行） ----
        if step_filepath:
            bbox = _get_bbox_from_step(step_filepath)
            if bbox:
                bbox_result = validate_bounding_box(
                    bbox, drawing_spec.overall_dimensions
                )
                if not bbox_result.passed:
                    logger.warning(
                        f"Smart refiner Layer 2: bbox validation — "
                        f"{bbox_result.detail} (VL will still run)"
                    )
                    static_notes.append(
                        f"包围盒偏差: 实际 X={bbox[0]:.1f} Y={bbox[1]:.1f} Z={bbox[2]:.1f}, "
                        f"预期: {drawing_spec.overall_dimensions} ({bbox_result.detail})"
                    )
                else:
                    logger.info("Smart refiner Layer 2: bbox validation PASSED")
            else:
                logger.warning("Smart refiner Layer 2: could not read STEP bbox, skipping")
        else:
            logger.info("Smart refiner Layer 2: no step_filepath, skipping bbox check")

        # ---- Layer 3: VL 对比（始终运行，是质量的唯一裁判） ----
        logger.info("Smart refiner Layer 3: running VL comparison...")
        comparison = self.compare_chain.invoke({
            "drawing_spec": drawing_spec.to_prompt_text(),
            "code": code,
            "original_image_type": original_image.type,
            "original_image_data": original_image.data,
            "rendered_image_type": rendered_image.type,
            "rendered_image_data": rendered_image.data,
        })["result"]

        if comparison is None:
            logger.info("Smart refiner Layer 3: PASS — rendering matches drawing")
            return None

        logger.info(f"Smart refiner Layer 3: found differences:\n{comparison}")

        # 合并 VL 发现 + 静态检查诊断，提升 Coder 修复精度
        if static_notes:
            fix_instructions = (
                comparison
                + "\n\n## 静态检查补充（供参考）\n"
                + "\n".join(f"- {n}" for n in static_notes)
            )
            logger.info(
                f"Smart refiner: Coder fix with VL findings + {len(static_notes)} static notes"
            )
        else:
            fix_instructions = comparison

        result = self.fix_chain.invoke({
            "code": code,
            "fix_instructions": fix_instructions,
        })["result"]

        return result
