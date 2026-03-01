"""Printability checker — validates geometry against print technology constraints.

Operates on pre-computed ``geometry_info`` dicts so the checker is decoupled
from the CAD kernel.  Three built-in preset profiles are provided for
FDM, SLA, and SLS technologies.

Advanced analysis methods (orientation, supports, material, time, corrections)
are available on ``PrintabilityChecker`` for post-check optimisation advice.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from backend.models.printability import (
    PrintabilityResult,
    PrintIssue,
    PrintProfile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Advanced analysis data classes
# ---------------------------------------------------------------------------


@dataclass
class OrientationAdvice:
    """Recommended print orientation."""

    axis: str  # "X", "Y", "Z"
    rotation_deg: float
    reason: str
    estimated_support_area_cm2: float


@dataclass
class SupportAdvice:
    """Support strategy recommendation."""

    strategy: str  # "tree", "linear", "none"
    density_percent: float
    reason: str


@dataclass
class MaterialEstimate:
    """Material usage estimate."""

    filament_length_m: float
    filament_weight_g: float
    cost_estimate_cny: float  # rough cost at 80 CNY/kg


@dataclass
class TimeEstimate:
    """Print time estimate."""

    total_minutes: float
    layer_count: int
    per_layer_seconds: float


@dataclass
class CorrectionAdvice:
    """Correction suggestion for a printability issue."""

    issue_type: str
    suggestion: str
    auto_fixable: bool

# ---------------------------------------------------------------------------
# Preset profiles
# ---------------------------------------------------------------------------

PRESET_PROFILES: dict[str, PrintProfile] = {
    "fdm_standard": PrintProfile(
        name="fdm_standard",
        technology="FDM",
        min_wall_thickness=0.8,
        max_overhang_angle=45.0,
        min_hole_diameter=2.0,
        min_rib_thickness=0.8,
        build_volume=(220, 220, 250),
    ),
    "sla_standard": PrintProfile(
        name="sla_standard",
        technology="SLA",
        min_wall_thickness=0.3,
        max_overhang_angle=30.0,
        min_hole_diameter=0.5,
        min_rib_thickness=0.3,
        build_volume=(145, 145, 175),
    ),
    "sls_standard": PrintProfile(
        name="sls_standard",
        technology="SLS",
        min_wall_thickness=0.7,
        max_overhang_angle=90.0,  # SLS is self-supporting
        min_hole_diameter=1.5,
        min_rib_thickness=0.7,
        build_volume=(300, 300, 300),
    ),
}


# ---------------------------------------------------------------------------
# PrintabilityChecker
# ---------------------------------------------------------------------------


class PrintabilityChecker:
    """Check pre-computed geometry info against a print profile.

    The checker does **not** operate on CAD geometry directly.  Instead it
    receives a ``geometry_info`` dict with pre-extracted measurements:

    - ``bounding_box``: ``{"x": float, "y": float, "z": float}`` in mm
    - ``min_wall_thickness``: minimum wall thickness in mm
    - ``max_overhang_angle``: maximum overhang angle in degrees
    - ``min_hole_diameter``: minimum hole diameter in mm
    - ``min_rib_thickness``: minimum rib thickness in mm
    - ``volume_cm3``: part volume in cm³

    Missing fields are silently skipped (no issue generated).
    """

    def check(
        self,
        geometry_info: dict,
        profile: str | PrintProfile = "fdm_standard",
    ) -> PrintabilityResult:
        """Run all printability checks and return an aggregated result.

        Parameters:
            geometry_info: Pre-computed geometry measurements.
            profile: Profile name (string key into ``PRESET_PROFILES``) or
                a ``PrintProfile`` instance.

        Raises:
            ValueError: If *profile* is a string that does not match any
                preset profile name.
        """
        prof = self._resolve_profile(profile)

        issues: list[PrintIssue] = []

        for issue in (
            self._check_wall_thickness(
                geometry_info.get("min_wall_thickness"),
                prof.min_wall_thickness,
            ),
            self._check_overhang(
                geometry_info.get("max_overhang_angle"),
                prof.max_overhang_angle,
            ),
            self._check_hole_diameter(
                geometry_info.get("min_hole_diameter"),
                prof.min_hole_diameter,
            ),
            self._check_rib_thickness(
                geometry_info.get("min_rib_thickness"),
                prof.min_rib_thickness,
            ),
            self._check_build_volume(
                geometry_info.get("bounding_box"),
                prof.build_volume,
            ),
        ):
            if issue is not None:
                issues.append(issue)

        printable = all(i.severity != "error" for i in issues)

        bbox = geometry_info.get("bounding_box")
        volume = geometry_info.get("volume_cm3")

        return PrintabilityResult(
            printable=printable,
            profile=prof.name,
            issues=issues,
            material_volume_cm3=volume,
            bounding_box=bbox,
        )

    # -- individual checks ---------------------------------------------------

    @staticmethod
    def _check_wall_thickness(
        value: Optional[float],
        threshold: float,
    ) -> Optional[PrintIssue]:
        if value is None:
            return None
        if value < threshold:
            return PrintIssue(
                check="wall_thickness",
                severity="error",
                message=(
                    f"Wall thickness {value:.2f} mm is below "
                    f"minimum {threshold:.2f} mm"
                ),
                value=value,
                threshold=threshold,
                suggestion=(
                    "Increase wall thickness or switch to a higher-"
                    "resolution print technology (e.g. SLA)."
                ),
            )
        return None

    @staticmethod
    def _check_overhang(
        value: Optional[float],
        threshold: float,
    ) -> Optional[PrintIssue]:
        if value is None:
            return None
        if value > threshold:
            return PrintIssue(
                check="overhang",
                severity="warning",
                message=(
                    f"Overhang angle {value:.1f}\u00b0 exceeds "
                    f"maximum {threshold:.1f}\u00b0"
                ),
                value=value,
                threshold=threshold,
                suggestion=(
                    "Add support structures, reorient the part, or "
                    "consider SLS printing (no supports needed)."
                ),
            )
        return None

    @staticmethod
    def _check_hole_diameter(
        value: Optional[float],
        threshold: float,
    ) -> Optional[PrintIssue]:
        if value is None:
            return None
        if value < threshold:
            return PrintIssue(
                check="hole_diameter",
                severity="error",
                message=(
                    f"Hole diameter {value:.2f} mm is below "
                    f"minimum {threshold:.2f} mm"
                ),
                value=value,
                threshold=threshold,
                suggestion=(
                    "Enlarge the hole or drill it in post-processing."
                ),
            )
        return None

    @staticmethod
    def _check_rib_thickness(
        value: Optional[float],
        threshold: float,
    ) -> Optional[PrintIssue]:
        if value is None:
            return None
        if value < threshold:
            return PrintIssue(
                check="rib_thickness",
                severity="warning",
                message=(
                    f"Rib thickness {value:.2f} mm is below "
                    f"minimum {threshold:.2f} mm"
                ),
                value=value,
                threshold=threshold,
                suggestion=(
                    "Thicken ribs or remove thin features."
                ),
            )
        return None

    @staticmethod
    def _check_build_volume(
        bbox: Optional[dict[str, float]],
        build_volume: tuple[float, float, float],
    ) -> Optional[PrintIssue]:
        if bbox is None:
            return None
        bx, by, bz = build_volume
        exceeded: list[str] = []
        if bbox.get("x", 0) > bx:
            exceeded.append(f"X ({bbox['x']:.1f} > {bx:.1f})")
        if bbox.get("y", 0) > by:
            exceeded.append(f"Y ({bbox['y']:.1f} > {by:.1f})")
        if bbox.get("z", 0) > bz:
            exceeded.append(f"Z ({bbox['z']:.1f} > {bz:.1f})")
        if exceeded:
            return PrintIssue(
                check="build_volume",
                severity="error",
                message=(
                    f"Part exceeds build volume: {', '.join(exceeded)}"
                ),
                suggestion=(
                    "Scale down the part or use a larger printer."
                ),
            )
        return None

    # -- advanced analysis ---------------------------------------------------

    def recommend_orientation(
        self, geometry_info: dict
    ) -> OrientationAdvice:
        """Recommend optimal print orientation.

        Analyses bounding box to find orientation with minimal overhang.
        Prefers orientation where the largest flat face is the base.
        """
        bbox = geometry_info.get("bounding_box")
        if not bbox:
            return OrientationAdvice(
                axis="Z",
                rotation_deg=0,
                reason="无包围盒信息，使用默认Z轴朝上方向",
                estimated_support_area_cm2=0,
            )

        x = bbox.get("x", 0)
        y = bbox.get("y", 0)
        z = bbox.get("z", 0)

        # Face areas for each orientation
        xy = x * y  # base area if Z-up
        xz = x * z  # base area if Y-up
        yz = y * z  # base area if X-up

        if xy >= xz and xy >= yz:
            axis, rotation = "Z", 0.0
            support_area = min(xz, yz) * 0.1
            reason = f"Z轴朝上: XY面({x:.0f}×{y:.0f})最大，悬挑最少"
        elif xz >= xy and xz >= yz:
            axis, rotation = "Y", 90.0
            support_area = min(xy, yz) * 0.1
            reason = f"Y轴朝上: XZ面({x:.0f}×{z:.0f})最大，悬挑最少"
        else:
            axis, rotation = "X", 90.0
            support_area = min(xy, xz) * 0.1
            reason = f"X轴朝上: YZ面({y:.0f}×{z:.0f})最大，悬挑最少"

        return OrientationAdvice(
            axis=axis,
            rotation_deg=rotation,
            reason=reason,
            estimated_support_area_cm2=support_area / 100,  # mm² → cm²
        )

    def suggest_supports(
        self, profile: PrintProfile, geometry_info: dict
    ) -> SupportAdvice:
        """Suggest support strategy based on profile and geometry."""
        tech = profile.technology.upper()

        if tech == "SLS":
            return SupportAdvice(
                strategy="none",
                density_percent=0.0,
                reason="SLS粉末床自支撑，无需额外支撑",
            )

        overhang = geometry_info.get("max_overhang_angle", 0)

        if overhang <= profile.max_overhang_angle:
            return SupportAdvice(
                strategy="none",
                density_percent=0.0,
                reason=(
                    f"悬挑角度{overhang:.0f}°在"
                    f"阈值{profile.max_overhang_angle:.0f}°以内"
                ),
            )

        if tech == "FDM":
            return SupportAdvice(
                strategy="tree",
                density_percent=15.0,
                reason=(
                    f"FDM悬挑{overhang:.0f}°超过"
                    f"{profile.max_overhang_angle:.0f}°，推荐树形支撑"
                ),
            )

        # SLA or other
        return SupportAdvice(
            strategy="linear",
            density_percent=20.0,
            reason=(
                f"悬挑{overhang:.0f}°超过"
                f"{profile.max_overhang_angle:.0f}°，推荐线性支撑"
            ),
        )

    def estimate_material(
        self, geometry_info: dict, infill_percent: float = 20.0
    ) -> MaterialEstimate:
        """Estimate material usage based on volume and infill."""
        volume = geometry_info.get("volume_cm3") or 0
        if volume <= 0:
            return MaterialEstimate(
                filament_length_m=0,
                filament_weight_g=0,
                cost_estimate_cny=0,
            )

        # Effective volume: shell (~30%) + internal infill
        shell_fraction = 0.3
        infill_fraction = 0.7 * infill_percent / 100.0
        effective_volume = volume * (shell_fraction + infill_fraction)

        # PLA density 1.24 g/cm³
        density_g_per_cm3 = 1.24
        weight_g = effective_volume * density_g_per_cm3

        # Filament diameter 1.75 mm → cross-section area in cm²
        filament_diameter_cm = 0.175
        cross_section_cm2 = math.pi * (filament_diameter_cm / 2) ** 2
        length_m = (effective_volume / cross_section_cm2) / 100

        # Cost at 80 CNY/kg
        cost_cny = weight_g / 1000 * 80

        return MaterialEstimate(
            filament_length_m=round(length_m, 2),
            filament_weight_g=round(weight_g, 1),
            cost_estimate_cny=round(cost_cny, 2),
        )

    def estimate_print_time(
        self,
        geometry_info: dict,
        layer_height: float = 0.2,
        print_speed: float = 50.0,
    ) -> TimeEstimate:
        """Estimate print time based on layer count and speed."""
        bbox = geometry_info.get("bounding_box")
        if not bbox:
            return TimeEstimate(
                total_minutes=0, layer_count=0, per_layer_seconds=0
            )

        z = bbox.get("z", 0)
        x = bbox.get("x", 0)
        y = bbox.get("y", 0)

        layer_count = int(z / layer_height) if layer_height > 0 else 0

        # Rough estimate: nozzle traverses cross-section with ~0.4 mm line width
        nozzle_width = 0.4
        per_layer_seconds = (
            (x * y) / (print_speed * nozzle_width)
            if print_speed > 0
            else 0
        )

        total_minutes = (layer_count * per_layer_seconds) / 60

        return TimeEstimate(
            total_minutes=round(total_minutes, 1),
            layer_count=layer_count,
            per_layer_seconds=round(per_layer_seconds, 2),
        )

    def suggest_corrections(
        self, issues: list[PrintIssue]
    ) -> list[CorrectionAdvice]:
        """Generate correction suggestions for each issue."""
        if not issues:
            return []
        return [self._correction_for_issue(issue) for issue in issues]

    _CORRECTION_MAP: dict[str, tuple[str, bool]] = {
        "wall_thickness": ("增加壁厚至最小阈值以上，或更换高精度打印技术（如SLA）", True),
        "overhang": ("添加支撑结构、调整打印方向，或考虑使用SLS打印（无需支撑）", False),
        "hole_diameter": ("增大孔径至最小可打印直径以上，或后处理钻孔", True),
        "rib_thickness": ("增加筋板厚度，或移除过薄特征", True),
        "build_volume": ("缩小零件尺寸，或使用更大打印机", False),
    }

    @classmethod
    def _correction_for_issue(cls, issue: PrintIssue) -> CorrectionAdvice:
        entry = cls._CORRECTION_MAP.get(issue.check)
        if entry:
            suggestion, auto_fixable = entry
            return CorrectionAdvice(
                issue_type=issue.check,
                suggestion=suggestion,
                auto_fixable=auto_fixable,
            )
        return CorrectionAdvice(
            issue_type=issue.check,
            suggestion=f"请检查并修正: {issue.message}",
            auto_fixable=False,
        )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _resolve_profile(profile: str | PrintProfile) -> PrintProfile:
        if isinstance(profile, PrintProfile):
            return profile
        if profile not in PRESET_PROFILES:
            available = ", ".join(sorted(PRESET_PROFILES))
            raise ValueError(
                f"Unknown profile '{profile}'. "
                f"Available presets: {available}"
            )
        return PRESET_PROFILES[profile]
