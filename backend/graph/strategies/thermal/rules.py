"""RulesThermalStrategy — geometry-based thermal risk assessment.

Evaluates 3D print thermal risk from geometric features:
1. Aspect ratio (height/min_width) — tall thin parts warp
2. Overhang area ratio — unsupported overhangs concentrate heat
3. Cross-section variation — sudden area changes cause thermal stress
4. Large flat surfaces — prone to warping/curling
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import trimesh

from backend.graph.descriptor import NodeStrategy

logger = logging.getLogger(__name__)


class RulesThermalStrategy(NodeStrategy):
    """Geometry rules-based thermal risk assessment."""

    def analyze(self, mesh: trimesh.Trimesh) -> dict[str, Any]:
        """Analyze mesh for thermal risk factors."""
        config = self.config
        risk_factors: list[dict[str, Any]] = []
        score = 0.0

        extents = mesh.bounding_box.extents
        min_xy = min(extents[0], extents[1])
        max_z = extents[2]

        # 1. Aspect ratio check
        aspect_ratio = max_z / max(min_xy, 1e-6)
        if aspect_ratio > config.aspect_ratio_threshold:
            risk_factors.append(
                {
                    "type": "aspect_ratio",
                    "description": (
                        f"高宽比 {aspect_ratio:.1f} 超过阈值"
                        f" {config.aspect_ratio_threshold}，"
                        "打印过程中可能发生层间剥离或翘曲"
                    ),
                    "severity": "high",
                    "value": round(aspect_ratio, 2),
                }
            )
            score += 30
        elif aspect_ratio > config.aspect_ratio_threshold * 0.5:
            risk_factors.append(
                {
                    "type": "aspect_ratio",
                    "description": (f"高宽比 {aspect_ratio:.1f} 偏高，注意打印稳定性"),
                    "severity": "medium",
                    "value": round(aspect_ratio, 2),
                }
            )
            score += 15

        # 2. Overhang analysis (exclude bottom-layer faces on build plate)
        face_normals = mesh.face_normals
        face_areas = mesh.area_faces
        face_centers = mesh.triangles_center
        z_min_bound = mesh.bounds[0][2]
        bottom_layer_tol = max_z * 0.05  # bottom 5% is build plate zone
        overhang_mask = face_normals[:, 2] < -np.cos(
            np.radians(config.overhang_threshold)
        )
        # Exclude faces sitting on the build plate
        not_on_plate = face_centers[:, 2] > (z_min_bound + bottom_layer_tol)
        overhang_mask = overhang_mask & not_on_plate
        overhang_area = float(np.sum(face_areas[overhang_mask]))
        total_area = float(np.sum(face_areas))
        overhang_ratio = overhang_area / max(total_area, 1e-6)

        if overhang_ratio > 0.3:
            risk_factors.append(
                {
                    "type": "overhang",
                    "description": (
                        f"悬挑面积占比 {overhang_ratio:.0%}，热应力集中风险高"
                    ),
                    "severity": "high",
                    "value": round(overhang_ratio, 4),
                }
            )
            score += 25
        elif overhang_ratio > 0.1:
            risk_factors.append(
                {
                    "type": "overhang",
                    "description": (
                        f"悬挑面积占比 {overhang_ratio:.0%}，存在一定热风险"
                    ),
                    "severity": "medium",
                    "value": round(overhang_ratio, 4),
                }
            )
            score += 10

        # 3. Cross-section variation
        z_min, z_max = mesh.bounds[0][2], mesh.bounds[1][2]
        n_slices = 10
        areas: list[float] = []
        for i in range(n_slices):
            z = z_min + (z_max - z_min) * (i + 0.5) / n_slices
            try:
                section = mesh.section(
                    plane_origin=[0, 0, z],
                    plane_normal=[0, 0, 1],
                )
                if section is not None:
                    planar, _ = section.to_planar()
                    areas.append(float(planar.area))
                else:
                    areas.append(0.0)
            except Exception:
                areas.append(0.0)

        if len(areas) >= 2 and max(areas) > 0:
            area_variation = (max(areas) - min(areas)) / max(areas)
            if area_variation > 0.7:
                risk_factors.append(
                    {
                        "type": "cross_section_variation",
                        "description": (
                            f"截面积变化率 {area_variation:.0%}，"
                            "急剧变化处易产生热应力集中"
                        ),
                        "severity": "medium",
                        "value": round(area_variation, 4),
                    }
                )
                score += 15

        # 4. Large flat bottom surface (warping risk)
        bottom_mask = face_normals[:, 2] < -0.9
        if np.any(bottom_mask):
            bottom_area = float(np.sum(face_areas[bottom_mask]))
            if bottom_area > config.large_flat_area_threshold:
                risk_factors.append(
                    {
                        "type": "large_flat_area",
                        "description": (
                            f"底部平面面积 {bottom_area:.0f} mm² 较大，" "翘曲风险升高"
                        ),
                        "severity": "medium",
                        "value": round(bottom_area, 2),
                    }
                )
                score += 10

        # Determine risk level
        score = min(score, 100)
        if score >= 50:
            risk_level = "high"
        elif score >= 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        recommendations = self._generate_recommendations(risk_factors)

        return {
            "risk_level": risk_level,
            "risk_score": round(score, 1),
            "risk_factors": risk_factors,
            "recommendations": recommendations,
            "geometry_summary": {
                "extents": [round(float(e), 2) for e in extents],
                "aspect_ratio": round(aspect_ratio, 2),
                "overhang_ratio": round(overhang_ratio, 4),
                "volume_cm3": round(float(mesh.volume) / 1000, 2),
            },
        }

    @staticmethod
    def _generate_recommendations(
        risk_factors: list[dict[str, Any]],
    ) -> list[str]:
        recs: list[str] = []
        types = {f["type"] for f in risk_factors}
        if "aspect_ratio" in types:
            recs.append("考虑将零件分割打印后拼接，或增加底部支撑面积")
        if "overhang" in types:
            recs.append("添加支撑结构或调整打印方向以减少悬挑")
        if "cross_section_variation" in types:
            recs.append("在截面突变处降低打印速度，减少层间热应力")
        if "large_flat_area" in types:
            recs.append("使用 Brim 或 Raft 增加底面附着力，防止翘曲")
        if not recs:
            recs.append("几何形状适合打印，无特殊热风险")
        return recs

    async def execute(self, ctx: Any) -> None:
        """Execute thermal risk assessment."""
        import asyncio

        asset = ctx.get_asset("final_mesh")
        mesh = await asyncio.to_thread(trimesh.load, asset.path, force="mesh")

        await ctx.dispatch_progress(1, 2, "热风险评估中")

        report = await asyncio.to_thread(self.analyze, mesh)

        ctx.put_data("thermal_report", report)
        ctx.put_data("thermal_simulation_status", "completed")

        await ctx.dispatch_progress(2, 2, f"热风险评估完成: {report['risk_level']}")
