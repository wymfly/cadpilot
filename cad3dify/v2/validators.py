"""Static code parameter validator for CadQuery generated code.

Extracts numeric variable assignments from generated CadQuery code via
Python AST and compares them against expected values from a DrawingSpec.
This is the first line of defense — catching obvious parameter mismatches
before expensive VL model calls.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..knowledge.part_types import DrawingSpec


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Result of static parameter validation."""

    passed: bool
    mismatches: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extracted_values: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------

# Keywords that hint a variable holds a relevant numeric dimension.
_DIMENSION_KEYWORDS: set[str] = {
    "diameter",
    "height",
    "radius",
    "bore",
    "depth",
    "width",
    "length",
    "thickness",
    "pcd",
    "count",
    "wall",
    "d",
    "h",
    "r",
    "w",
    "l",
}


def _is_numeric_node(node: ast.expr) -> float | None:
    """Return the numeric value if *node* is a constant number, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    # Handle negative numbers: ast.UnaryOp(op=USub(), operand=Constant(...))
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return -float(node.operand.value)
    return None


def extract_numeric_assignments(code: str) -> dict[str, float]:
    """Parse *code* with ``ast`` and return ``{var_name: value}`` for all
    numeric variable assignments.

    Supports:
    - Simple assignments: ``x = 100``
    - Tuple unpacking: ``a, b, c = 1, 2, 3``
    """
    result: dict[str, float] = {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        logger.warning("Failed to parse code with ast — skipping extraction")
        return result

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        # --- simple assignment: x = 100 ---
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            value = _is_numeric_node(node.value)
            if value is not None:
                result[node.targets[0].id] = value

        # --- tuple unpacking: a, b, c = 1, 2, 3 ---
        elif (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Tuple)
            and isinstance(node.value, ast.Tuple)
            and len(node.targets[0].elts) == len(node.value.elts)
        ):
            for target_elt, value_elt in zip(
                node.targets[0].elts, node.value.elts
            ):
                if isinstance(target_elt, ast.Name):
                    v = _is_numeric_node(value_elt)
                    if v is not None:
                        result[target_elt.id] = v

    return result


# ---------------------------------------------------------------------------
# Spec collection
# ---------------------------------------------------------------------------


def collect_spec_values(spec: DrawingSpec) -> dict[str, float]:
    """Flatten a :class:`DrawingSpec` into ``{label: expected_value}`` pairs
    that correspond to typical variable names in generated CadQuery code.

    Categories:
    - ``profile_*``: diameters/heights from ``base_body.profile``
    - ``bore_diameter``: central bore
    - ``feature_*``: hole pattern / bolt circle parameters
    - ``overall_*``: overall dimensions
    - ``base_*``: base body scalar fields (width, length, height, wall_thickness)
    """
    values: dict[str, float] = {}

    # Profile layers
    for i, layer in enumerate(spec.base_body.profile):
        values[f"profile_{i}_diameter"] = layer.diameter
        values[f"profile_{i}_height"] = layer.height

    # Bore
    if spec.base_body.bore is not None:
        values["bore_diameter"] = spec.base_body.bore.diameter
        if spec.base_body.bore.depth is not None:
            values["bore_depth"] = spec.base_body.bore.depth

    # Base body scalar dimensions
    for attr in ("width", "length", "height", "wall_thickness"):
        v = getattr(spec.base_body, attr, None)
        if v is not None:
            values[f"base_{attr}"] = v

    # Overall dimensions
    for key, v in spec.overall_dimensions.items():
        values[f"overall_{key}"] = v

    # Features (hole patterns, etc.)
    for i, feat in enumerate(spec.features):
        if isinstance(feat.spec, dict):
            feat_data = feat.spec
        else:
            feat_data = feat.spec.model_dump()
        for key in ("diameter", "pcd", "count"):
            if key in feat_data:
                values[f"feature_{i}_{key}"] = float(feat_data[key])

    return values


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

# Default relative tolerance (5 %).
DEFAULT_TOLERANCE: float = 0.05


def _values_match(actual: float, expected: float, tol: float) -> bool:
    """Return True if *actual* is within *tol* relative tolerance of *expected*."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / abs(expected) <= tol


def _name_match_score(spec_label: str, var_name: str) -> float:
    """Return a relevance score (0.0–1.0) between a spec label and a code
    variable name.

    The score is the fraction of *semantic* spec tokens that appear in the
    variable name.  Single-character tokens (``d``, ``h``, ``r``, …) are
    treated as weak matches — they contribute only when *no* better multi-char
    token matched.

    Tokens that are purely numeric (layer indices) are excluded from scoring.
    """
    raw_tokens = [t for t in spec_label.split("_") if t and not t.isdigit()]
    if not raw_tokens:
        return 0.0

    var_lower = var_name.lower()

    # Partition into strong (multi-char) and weak (single-char) tokens.
    strong = [t for t in raw_tokens if len(t) > 1]
    weak = [t for t in raw_tokens if len(t) == 1]

    strong_hits = sum(1 for t in strong if t in var_lower)
    weak_hits = sum(1 for t in weak if t in var_lower)

    if strong:
        # Only count strong-token matches.  Weak tokens are a bonus but
        # cannot elevate the score alone.
        return strong_hits / len(strong)
    # Label has *only* weak tokens (rare).  Fall back to weak scoring.
    if weak:
        return weak_hits / len(weak)
    return 0.0


# Minimum name-match score required to consider a variable a "confident"
# name-based candidate.  With e.g. tokens {"bore", "diameter"} a variable
# must match at least one strong token (score >= 0.5).
_MIN_NAME_SCORE: float = 0.5


def _find_best_code_match(
    spec_label: str,
    expected: float,
    extracted: dict[str, float],
    tol: float,
) -> tuple[str | None, float | None, bool]:
    """Try to find a code variable that matches *expected*.

    Strategy (in order):
    1. **Strong name match + value match** — variable name scores above
       ``_MIN_NAME_SCORE`` *and* value is within tolerance.
    2. **Pure value match** — any extracted variable whose value is within
       tolerance of *expected*.
    3. **Strong name match + value mismatch** — confident name match but
       the value is wrong.  This is the only case that produces a hard
       ``is_match=False`` with a non-``None`` candidate.

    Returns ``(matched_var, actual_value, is_match)``.
    """
    # Score every extracted variable against the spec label.
    scored: list[tuple[str, float, float]] = []  # (var, val, score)
    for var, val in extracted.items():
        s = _name_match_score(spec_label, var)
        if s >= _MIN_NAME_SCORE:
            scored.append((var, val, s))

    # Sort by descending score so the best name-match is tried first.
    scored.sort(key=lambda x: x[2], reverse=True)

    # Pass 1 — strong name match + value match
    for var, val, _score in scored:
        if _values_match(val, expected, tol):
            return var, val, True

    # Pass 2 — pure value match (any variable with close enough value)
    for var, val in extracted.items():
        if _values_match(val, expected, tol):
            return var, val, True

    # Pass 3 — strong name match exists but value is wrong → mismatch
    if scored:
        best_var, best_val, _ = scored[0]
        return best_var, best_val, False

    # No match at all
    return None, None, False


# ---------------------------------------------------------------------------
# Hard-fail vs soft-warn classification
# ---------------------------------------------------------------------------

# Spec labels whose absence or mismatch produces a WARNING rather than FAIL.
_SOFT_LABELS: set[str] = {"bore_diameter", "bore_depth"}


def _is_soft(spec_label: str) -> bool:
    return spec_label in _SOFT_LABELS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_code_params(
    code: str,
    spec: DrawingSpec,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> ValidationResult:
    """Validate numeric parameters in *code* against *spec*.

    Parameters
    ----------
    code:
        Generated CadQuery Python source code.
    spec:
        The drawing specification from the analyzer stage.
    tolerance:
        Relative tolerance for value comparison (default 5 %).

    Returns
    -------
    ValidationResult
        ``passed`` is ``True`` only when there are zero hard mismatches.
    """
    extracted = extract_numeric_assignments(code)
    expected = collect_spec_values(spec)

    mismatches: list[str] = []
    warnings: list[str] = []

    for label, exp_val in expected.items():
        var, actual, matched = _find_best_code_match(
            label, exp_val, extracted, tolerance
        )

        if matched:
            continue

        if var is not None and actual is not None:
            # A candidate variable was found but value is wrong.
            msg = (
                f"{label}: expected {exp_val}, found {actual} "
                f"(var '{var}', delta {abs(actual - exp_val):.2f})"
            )
        else:
            # No matching variable found at all.
            msg = f"{label}: expected {exp_val}, not found in code"

        if _is_soft(label):
            warnings.append(msg)
            logger.debug(f"Validator warning: {msg}")
        else:
            mismatches.append(msg)
            logger.debug(f"Validator mismatch: {msg}")

    passed = len(mismatches) == 0

    return ValidationResult(
        passed=passed,
        mismatches=mismatches,
        warnings=warnings,
        extracted_values=extracted,
    )


# ---------------------------------------------------------------------------
# Bounding-box validation
# ---------------------------------------------------------------------------


@dataclass
class BBoxResult:
    passed: bool = True
    detail: str = ""
    actual: tuple[float, float, float] = (0, 0, 0)
    expected: dict[str, float] = field(default_factory=dict)


def _get_bbox_from_step(step_filepath: str) -> tuple[float, float, float] | None:
    """从 STEP 文件读取包围盒 (xlen, ylen, zlen)"""
    try:
        import cadquery as cq
        shape = cq.importers.importStep(step_filepath)
        bb = shape.val().BoundingBox()
        return (bb.xlen, bb.ylen, bb.zlen)
    except Exception as e:
        logger.error(f"Failed to read bounding box from {step_filepath}: {e}")
        return None


def validate_bounding_box(
    actual_bbox: tuple[float, float, float],
    overall_dims: dict[str, float],
    tolerance: float = 0.10,
) -> BBoxResult:
    """
    Compare actual bounding box (xlen, ylen, zlen) with DrawingSpec.overall_dimensions.
    tolerance: relative error threshold (default 10%)

    Axis mapping rules:
    - total_height / height / thickness → best-matching axis (min relative error
      across X/Y/Z). CadQuery revolve(Y-axis) puts height on Y, extrude-Z puts
      it on Z; using the closest axis handles both without knowing part orientation.
    - max_diameter / diameter / length / total_length → max(X, Y)
      Works for both rotational parts (X≈Y≈diameter) and plates (max(X,Y)=length)
    - width → min(X, Y)  (plate secondary planar dimension)
    """
    result = BBoxResult(actual=actual_bbox, expected=overall_dims)
    mismatches = []

    # Height / thickness — check against the axis closest to the expected value.
    # This handles both revolve-around-Y (height→ylen) and extrude-Z (height→zlen).
    for key in ["total_height", "height", "thickness"]:
        if key in overall_dims:
            exp = overall_dims[key]
            if exp > 0:
                best_err = min(abs(actual_bbox[i] - exp) / exp for i in range(3))
                if best_err > tolerance:
                    closest_val = min(actual_bbox, key=lambda v: abs(v - exp))
                    mismatches.append(
                        f"Height: closest_axis={closest_val:.1f} vs spec {key}={exp} "
                        f"(diff {best_err:.0%})"
                    )

    # Primary planar dimension: diameter or length → max(X, Y)
    for key in ["max_diameter", "diameter", "length", "total_length"]:
        if key in overall_dims:
            exp = overall_dims[key]
            actual_planar = max(actual_bbox[0], actual_bbox[1])
            if exp > 0 and abs(actual_planar - exp) / exp > tolerance:
                mismatches.append(
                    f"Planar(max): actual={actual_planar:.1f} vs spec {key}={exp}"
                )

    # Secondary planar dimension: width → min(X, Y)
    if "width" in overall_dims:
        exp = overall_dims["width"]
        actual_planar_min = min(actual_bbox[0], actual_bbox[1])
        if exp > 0 and abs(actual_planar_min - exp) / exp > tolerance:
            mismatches.append(
                f"Planar(min): actual={actual_planar_min:.1f} vs spec width={exp}"
            )

    if mismatches:
        result.passed = False
        result.detail = "; ".join(mismatches)
    else:
        result.detail = "Bounding box within tolerance"

    logger.info(f"BBox validation: passed={result.passed}, actual={actual_bbox}, {result.detail}")
    return result


# ---------------------------------------------------------------------------
# STEP geometry validation
# ---------------------------------------------------------------------------


@dataclass
class GeometryResult:
    """Result of STEP file geometry validation."""
    is_valid: bool = False
    volume: float = 0.0
    bbox: tuple[float, float, float] | None = None  # (xlen, ylen, zlen)
    error: str = ""


def validate_step_geometry(step_filepath: str) -> GeometryResult:
    """Validate a STEP file: check isValid(), compute Volume and BoundingBox.

    Returns GeometryResult with is_valid=False if file doesn't exist or geometry is broken.
    """
    try:
        import cadquery as cq
        shape = cq.importers.importStep(step_filepath)
        solid = shape.val()
        bb = solid.BoundingBox()
        geo = GeometryResult(
            is_valid=solid.isValid(),
            volume=solid.Volume(),
            bbox=(bb.xlen, bb.ylen, bb.zlen),
        )
        logger.info(
            f"Geometry validation: valid={geo.is_valid}, "
            f"volume={geo.volume:.1f}, bbox={geo.bbox}"
        )
        return geo
    except FileNotFoundError:
        return GeometryResult(is_valid=False, error=f"File not found: {step_filepath}")
    except Exception as e:
        return GeometryResult(is_valid=False, error=str(e))
