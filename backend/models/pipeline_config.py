"""Pipeline configuration model with presets and tooltips.

Implements ADR-6: every enhancement step is independently toggleable.
Three presets (fast / balanced / precise) provide sensible defaults.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel


class PipelineConfig(BaseModel):
    """管道配置 — 每个增强步骤独立可控"""

    # --- 预设模式 ---
    preset: Literal["fast", "balanced", "precise", "custom"] = "balanced"

    # --- Stage 1: 图纸分析增强 ---
    ocr_assist: bool = False
    two_pass_analysis: bool = False
    multi_model_voting: bool = False
    self_consistency_runs: int = 1

    # --- Stage 2: 代码生成 ---
    best_of_n: int = 1
    rag_enabled: bool = True
    api_whitelist: bool = True
    ast_pre_check: bool = True

    # --- Stage 3: 验证 ---
    volume_check: bool = True
    topology_check: bool = True
    cross_section_check: bool = False

    # --- Stage 4: 修复循环 ---
    max_refinements: int = 3
    multi_view_render: bool = True
    structured_feedback: bool = True
    rollback_on_degrade: bool = True
    contour_overlay: bool = False

    # --- Stage 5: 输出 ---
    printability_check: bool = False
    output_formats: list[str] = ["step"]


class TooltipSpec(BaseModel):
    """Tooltip specification for a pipeline config field."""

    title: str
    description: str
    when_to_use: str
    cost: str
    default: str


PRESETS: dict[str, PipelineConfig] = {
    "fast": PipelineConfig(
        preset="fast",
        best_of_n=1,
        rag_enabled=False,
        multi_view_render=False,
        volume_check=False,
        topology_check=False,
        max_refinements=1,
        output_formats=["step"],
    ),
    "balanced": PipelineConfig(
        preset="balanced",
        best_of_n=3,
        rag_enabled=True,
        multi_view_render=True,
        volume_check=True,
        topology_check=True,
        max_refinements=3,
        output_formats=["step", "stl"],
    ),
    "precise": PipelineConfig(
        preset="precise",
        best_of_n=5,
        rag_enabled=True,
        multi_view_render=True,
        ocr_assist=True,
        two_pass_analysis=True,
        multi_model_voting=True,
        self_consistency_runs=3,
        volume_check=True,
        topology_check=True,
        cross_section_check=True,
        structured_feedback=True,
        contour_overlay=True,
        printability_check=True,
        output_formats=["step", "stl", "3mf"],
    ),
}


def _parse_pipeline_config(config_json: str) -> PipelineConfig:
    """Parse pipeline_config JSON string into PipelineConfig."""
    try:
        raw = json.loads(config_json)
    except json.JSONDecodeError:
        return PRESETS["balanced"]
    if not isinstance(raw, dict):
        return PRESETS["balanced"]
    preset = raw.get("preset", "balanced")
    if preset in PRESETS and len(raw) <= 2:  # only preset key (+ maybe extra)
        return PRESETS[preset]
    return PipelineConfig(**raw)


def get_tooltips() -> dict[str, TooltipSpec]:
    """Return tooltip specs for all configurable pipeline fields."""
    return {
        "ocr_assist": TooltipSpec(
            title="OCR 辅助",
            description="使用 OCR 提取图纸上的标注文字，增强尺寸识别准确率。",
            when_to_use="图纸标注密集或 VL 模型识别标注不准时",
            cost="增加 1-2 秒",
            default="balanced: 关闭",
        ),
        "two_pass_analysis": TooltipSpec(
            title="两阶段分析",
            description="先全局分析零件类型和整体结构，再局部分析细节特征。",
            when_to_use="复杂零件有多种特征时",
            cost="增加 1 次 VL 调用",
            default="balanced: 关闭",
        ),
        "multi_model_voting": TooltipSpec(
            title="多模型投票",
            description="同时使用多个 VL 模型分析，取一致结果。",
            when_to_use="高精度需求、关键零件",
            cost="耗时 ×2-3，Token ×2-3",
            default="balanced: 关闭",
        ),
        "self_consistency_runs": TooltipSpec(
            title="Self-Consistency",
            description="同一模型多次推理取一致性最高的结果。",
            when_to_use="模型输出不稳定时",
            cost="耗时 ×N",
            default="balanced: 1（关闭）",
        ),
        "best_of_n": TooltipSpec(
            title="多路生成 (Best-of-N)",
            description="生成 N 份候选代码并择优。N=3 时正确率从 40% 提升到 78%。",
            when_to_use="复杂零件、首次正确率不高时推荐开启",
            cost="耗时 ×N，Token ×N",
            default="balanced: N=3",
        ),
        "rag_enabled": TooltipSpec(
            title="RAG 检索增强",
            description="从知识库检索相似零件的成功代码作为 few-shot 示例。",
            when_to_use="有类似零件历史记录时效果最佳",
            cost="增加 0.5-1 秒检索时间",
            default="balanced: 开启",
        ),
        "api_whitelist": TooltipSpec(
            title="API 白名单",
            description="限制生成代码只使用经过验证的 CadQuery API 子集。",
            when_to_use="减少不可用 API 导致的执行失败",
            cost="无额外开销",
            default="balanced: 开启",
        ),
        "ast_pre_check": TooltipSpec(
            title="AST 静态检查",
            description="执行前对生成代码进行 AST 分析，检查语法和安全问题。",
            when_to_use="始终推荐开启",
            cost="无额外开销",
            default="balanced: 开启",
        ),
        "volume_check": TooltipSpec(
            title="体积验证",
            description="对比理论估算体积与实际生成体积，检测重大偏差。",
            when_to_use="有明确尺寸标注的零件",
            cost="增加 <0.5 秒",
            default="balanced: 开启",
        ),
        "topology_check": TooltipSpec(
            title="拓扑验证",
            description="检查生成几何体的拓扑有效性（闭合、无自交等）。",
            when_to_use="始终推荐开启",
            cost="增加 <0.5 秒",
            default="balanced: 开启",
        ),
        "cross_section_check": TooltipSpec(
            title="截面分析",
            description="在关键位置切截面，与图纸截面视图对比。",
            when_to_use="有截面视图的图纸",
            cost="增加 1-2 秒 + 1 次 VL 调用",
            default="balanced: 关闭",
        ),
        "max_refinements": TooltipSpec(
            title="最大修复轮数",
            description="VL 对比发现偏差后自动修复的最大轮数。",
            when_to_use="增加轮数可提高最终质量，但耗时更长",
            cost="每轮 1 次 VL + 1 次 Coder 调用",
            default="balanced: 3 轮",
        ),
        "multi_view_render": TooltipSpec(
            title="多视角渲染",
            description="渲染多个标准视角（前/顶/侧/等轴测）进行比对。",
            when_to_use="提升 VL 对比准确率",
            cost="增加渲染时间",
            default="balanced: 开启",
        ),
        "structured_feedback": TooltipSpec(
            title="结构化反馈",
            description="VL 模型输出结构化 JSON 问题列表，而非自由文本。",
            when_to_use="提升修复精准度",
            cost="无额外开销",
            default="balanced: 开启",
        ),
        "rollback_on_degrade": TooltipSpec(
            title="退化回滚",
            description="修复后质量下降时自动回滚到上一版本。",
            when_to_use="防止过度修复导致质量恶化",
            cost="无额外开销",
            default="balanced: 开启",
        ),
        "contour_overlay": TooltipSpec(
            title="轮廓叠加",
            description="将渲染轮廓叠加到原始图纸上进行像素级对比。",
            when_to_use="精确外形匹配需求",
            cost="增加 1-2 秒图像处理",
            default="balanced: 关闭",
        ),
        "printability_check": TooltipSpec(
            title="可打印性检查",
            description="检查模型是否适合 3D 打印（壁厚、悬垂角、支撑等）。",
            when_to_use="输出用于 3D 打印时",
            cost="增加 1-2 秒分析",
            default="balanced: 关闭",
        ),
        "output_formats": TooltipSpec(
            title="输出格式",
            description="选择输出的 3D 文件格式（STEP/STL/3MF）。",
            when_to_use="按需选择：STEP 用于 CAD，STL/3MF 用于打印",
            cost="每种额外格式增加转换时间",
            default="balanced: STEP + STL",
        ),
    }
