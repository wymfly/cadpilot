from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, model_validator


class PartType(str, Enum):
    """零件类型分类"""
    ROTATIONAL = "rotational"
    ROTATIONAL_STEPPED = "rotational_stepped"
    PLATE = "plate"
    BRACKET = "bracket"
    HOUSING = "housing"
    GEAR = "gear"
    GENERAL = "general"


class DimensionLayer(BaseModel):
    """阶梯层尺寸"""
    diameter: float
    height: float
    label: str = ""


class BoreSpec(BaseModel):
    """通孔/盲孔规格"""
    diameter: float
    through: bool = True
    depth: Optional[float] = None


class HolePatternSpec(BaseModel):
    """孔阵列规格"""
    pattern: str = "circular"
    count: int
    diameter: float
    pcd: Optional[float] = None
    spacing_x: Optional[float] = None
    spacing_y: Optional[float] = None
    on_layer: str = ""


class FilletSpec(BaseModel):
    """圆角规格"""
    radius: float
    locations: list[str] = []


class ChamferSpec(BaseModel):
    """倒角规格"""
    size: float
    locations: list[str] = []


class KeywaySpec(BaseModel):
    """键槽规格"""
    width: float
    depth: float
    length: float


class SlotSpec(BaseModel):
    """槽规格"""
    width: float
    depth: float
    length: Optional[float] = None


class Feature(BaseModel):
    """结构化特征 — 支持类型化 spec 或 dict fallback"""
    type: str
    spec: Union[HolePatternSpec, FilletSpec, ChamferSpec, KeywaySpec, SlotSpec, dict] = {}

    @model_validator(mode="before")
    @classmethod
    def _from_flat_dict(cls, values: Any) -> Any:
        """Convert flat dict like {"type": "fillet", "radius": 3} to Feature.

        When a plain dict without a ``spec`` key is passed, the ``type`` value
        is extracted and the remaining keys are placed into ``spec``.
        """
        if isinstance(values, dict) and "spec" not in values:
            feat_type = values.pop("type", "unknown")
            return {"type": feat_type, "spec": values}
        return values


class BaseBodySpec(BaseModel):
    """基体构建规格"""
    method: str  # revolve, extrude, loft, sweep, shell
    profile: list[DimensionLayer] = []
    bore: Optional[BoreSpec] = None
    width: Optional[float] = None
    length: Optional[float] = None
    height: Optional[float] = None
    wall_thickness: Optional[float] = None


class DrawingSpec(BaseModel):
    """图纸分析结构化结果 — VL 模型输出格式"""
    part_type: PartType
    description: str
    views: list[str] = []
    overall_dimensions: dict[str, float] = {}
    base_body: BaseBodySpec
    features: list[Feature] = []
    notes: list[str] = []

    def to_prompt_text(self) -> str:
        """将 DrawingSpec 转为 Coder 模型可读的文本描述"""
        lines = [
            f"## 零件规格",
            f"类型: {self.part_type.value}",
            f"描述: {self.description}",
            f"视图: {', '.join(self.views)}",
            f"总体尺寸: {self.overall_dimensions}",
            f"",
            f"## 基体",
            f"构建方法: {self.base_body.method}",
        ]
        if self.base_body.profile:
            lines.append("阶梯轮廓:")
            for layer in self.base_body.profile:
                lines.append(f"  - 直径 {layer.diameter}, 高度 {layer.height} ({layer.label})")
        if self.base_body.bore:
            lines.append(f"中心孔: 直径 {self.base_body.bore.diameter}, {'通孔' if self.base_body.bore.through else f'盲孔 深度{self.base_body.bore.depth}'}")
        if self.base_body.width:
            lines.append(f"宽度: {self.base_body.width}")
        if self.base_body.length:
            lines.append(f"长度: {self.base_body.length}")
        if self.base_body.height:
            lines.append(f"高度: {self.base_body.height}")
        lines.append("")
        if self.features:
            lines.append("## 特征")
            for i, feat in enumerate(self.features, 1):
                if isinstance(feat.spec, dict):
                    lines.append(f"  {i}. {feat.type}: {feat.spec}")
                else:
                    lines.append(f"  {i}. {feat.type}: {feat.spec.model_dump()}")
        if self.notes:
            lines.append("")
            lines.append("## 注释")
            for note in self.notes:
                lines.append(f"  - {note}")
        return "\n".join(lines)
