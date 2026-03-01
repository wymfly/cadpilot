from __future__ import annotations

import os
import re
from typing import Any

from langchain.chains import LLMChain, SequentialChain, TransformChain
from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.prompts.image import ImagePromptTemplate
from loguru import logger

from ..infra.image import ImageData
from ..knowledge.part_types import DrawingSpec
from .validators import (
    _get_bbox_from_step,
    compare_topology,
    count_topology,
    validate_bounding_box,
    validate_code_params,
)
from .vl_feedback import parse_vl_feedback

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

_STRUCTURED_COMPARE_PROMPT = """\
你是一位经验丰富的机械工程师。请对比以下图片：
1. 第一张是原始的 2D 工程图纸
2. 后续图片是根据代码生成的 3D 模型多视角渲染图

## 预期规格（来自图纸分析）
{drawing_spec}

## 当前代码
```python
{code}
```

## 任务
请仔细对比渲染结果与原始图纸，找出所有不一致的地方。

## 输出格式（严格 JSON）
```json
{{
    "verdict": "PASS" 或 "FAIL",
    "issues": [
        {{
            "type": "dimension" | "structural" | "feature" | "orientation",
            "severity": "high" | "medium" | "low",
            "description": "问题描述",
            "expected": "预期值",
            "actual": "实际值",
            "location": "问题位置"
        }}
    ]
}}
```

如果所有尺寸在 5% 误差范围内，且结构正确，输出 `{{"verdict": "PASS", "issues": []}}`。

## 判断标准（严格遵守）
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

    def __init__(self, structured: bool = False) -> None:
        compare_template = _STRUCTURED_COMPARE_PROMPT if structured else _COMPARE_PROMPT
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
                            template=compare_template,
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
        from ..infra.llm_config_manager import get_model_for_role

        llm = get_model_for_role("refiner_vl").create_chat_model()

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
        from ..infra.llm_config_manager import get_model_for_role

        llm = get_model_for_role("refiner_coder").create_chat_model()

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
        self.structured_compare_chain = SmartCompareChain(structured=True)
        self.fix_chain = SmartFixChain()

    def refine(
        self,
        code: str,
        original_image: ImageData,
        rendered_image: ImageData,
        drawing_spec: DrawingSpec,
        step_filepath: str | None = None,
        structured_feedback: bool = False,
        topology_check: bool = False,
        contour_overlay: bool = False,
    ) -> str | None:
        """
        零风险改进流程：Layer 1/2 仅用于诊断上下文，VL 始终运行（质量唯一裁判）。

        Layer 1（静态参数校验）和 Layer 2（包围盒校验）收集诊断信息并注入
        Coder 修复指令，但不跳过 VL 调用。VL 是决定是否需要修复的唯一依据。

        Args:
            code: 当前 CadQuery 代码
            original_image: 原始工程图纸图像
            rendered_image: 当前渲染的单视角图像
            drawing_spec: 图纸分析规格
            step_filepath: STEP 文件路径（用于包围盒/拓扑校验）
            structured_feedback: 启用结构化 JSON 反馈解析
            topology_check: 启用拓扑验证并注入诊断
            contour_overlay: 当 VL 判定 FAIL 时生成轮廓叠加图做精细差异分析

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

        # ---- Layer 2.5: 拓扑校验（诊断，不影响 VL 执行） ----
        if topology_check and step_filepath:
            try:
                topo = count_topology(step_filepath)
                if not topo.error:
                    # 估算预期孔数：特征中 hole_pattern 类型的 count 之和
                    expected_holes = 0
                    for feat in drawing_spec.features:
                        if feat.type == "hole_pattern":
                            feat_data = feat.spec if isinstance(feat.spec, dict) else feat.spec.model_dump()
                            expected_holes += int(feat_data.get("count", 0))
                    if drawing_spec.base_body.bore is not None:
                        expected_holes += 1

                    topo_cmp = compare_topology(topo, expected_holes=expected_holes)
                    if not topo_cmp.passed:
                        logger.warning(
                            f"Smart refiner Layer 2.5: topology mismatch — "
                            f"{'; '.join(topo_cmp.mismatches)} (VL will still run)"
                        )
                        static_notes.extend(topo_cmp.mismatches)
                    else:
                        logger.info("Smart refiner Layer 2.5: topology check PASSED")
                else:
                    logger.warning(
                        f"Smart refiner Layer 2.5: topology error — {topo.error}"
                    )
            except Exception as e:
                logger.warning(f"Smart refiner Layer 2.5: topology check failed — {e}")

        # ---- Layer 3: VL 对比（始终运行，是质量的唯一裁判） ----
        logger.info("Smart refiner Layer 3: running VL comparison...")
        chain = self.structured_compare_chain if structured_feedback else self.compare_chain
        comparison = chain.invoke({
            "drawing_spec": drawing_spec.to_prompt_text(),
            "code": code,
            "original_image_type": original_image.type,
            "original_image_data": original_image.data,
            "rendered_image_type": rendered_image.type,
            "rendered_image_data": rendered_image.data,
        })["result"]

        # 结构化反馈解析
        if structured_feedback and comparison is not None:
            feedback = parse_vl_feedback(comparison)
            if feedback.passed:
                logger.info("Smart refiner Layer 3: structured feedback PASS")
                comparison = None
            else:
                comparison = feedback.to_fix_instructions()
                logger.info(
                    f"Smart refiner Layer 3: structured feedback — "
                    f"{len(feedback.issues)} issues"
                )

        if comparison is None:
            logger.info("Smart refiner Layer 3: PASS — rendering matches drawing")
            return None

        logger.info(f"Smart refiner Layer 3: found differences:\n{comparison}")

        # ---- Layer 3.5: 轮廓叠加比对（可选，精细差异分析） ----
        if contour_overlay and step_filepath and original_image:
            try:
                import tempfile

                from ..infra.render import (
                    overlay_contour_on_drawing,
                    render_wireframe_contour,
                )

                with tempfile.TemporaryDirectory() as tmp_dir:
                    contour_path = os.path.join(tmp_dir, "contour.png")
                    render_wireframe_contour(step_filepath, contour_path)

                    # Save original drawing to temp file for overlay
                    drawing_path = os.path.join(tmp_dir, "drawing.png")
                    original_image.save(drawing_path)

                    overlay_path = os.path.join(tmp_dir, "overlay.png")
                    overlay_contour_on_drawing(
                        drawing_path, contour_path, overlay_path
                    )

                    # Load overlay as ImageData for VL re-analysis
                    overlay_img = ImageData.load_from_file(overlay_path)
                    overlay_comparison = chain.invoke({
                        "drawing_spec": drawing_spec.to_prompt_text(),
                        "code": code,
                        "original_image_type": overlay_img.type,
                        "original_image_data": overlay_img.data,
                        "rendered_image_type": rendered_image.type,
                        "rendered_image_data": rendered_image.data,
                    })["result"]

                    if overlay_comparison:
                        comparison += (
                            "\n\n## 轮廓叠加精细分析\n" + overlay_comparison
                        )
                        logger.info(
                            "Smart refiner Layer 3.5: contour overlay "
                            "analysis added to fix instructions"
                        )
            except Exception as e:
                logger.warning(
                    f"Smart refiner Layer 3.5: contour overlay failed — {e}"
                )

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
