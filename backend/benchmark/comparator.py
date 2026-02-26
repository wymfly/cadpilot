"""Benchmark comparison — baseline vs enhanced metrics."""

from __future__ import annotations

from .metrics import BenchmarkMetrics

# Metrics where lower is better
_LOWER_IS_BETTER: frozenset[str] = frozenset({"avg_duration_s", "avg_tokens"})

_METRIC_LABELS: dict[str, str] = {
    "compile_rate": "编译率",
    "type_accuracy": "类型准确率",
    "param_accuracy_p50": "参数准确率 (P50)",
    "bbox_match_rate": "几何匹配率",
    "avg_duration_s": "平均耗时",
    "avg_tokens": "平均 Token",
}

# Metrics that represent rates (0..1 displayed as %)
_RATE_METRICS: frozenset[str] = frozenset({
    "compile_rate",
    "type_accuracy",
    "param_accuracy_p50",
    "bbox_match_rate",
})


def compute_comparison(
    baseline: BenchmarkMetrics, enhanced: BenchmarkMetrics
) -> dict[str, dict]:
    """Compute per-metric comparison between baseline and enhanced runs.

    For each metric: {"baseline": val, "enhanced": val, "delta": val, "improved": bool}
    For _LOWER_IS_BETTER metrics, improvement means delta < 0.
    """
    comparison: dict[str, dict] = {}

    for field in _METRIC_LABELS:
        b_val = getattr(baseline, field)
        e_val = getattr(enhanced, field)
        delta = e_val - b_val

        if field in _LOWER_IS_BETTER:
            improved = delta < 0
        else:
            improved = delta > 0

        comparison[field] = {
            "baseline": b_val,
            "enhanced": e_val,
            "delta": delta,
            "improved": improved,
        }

    return comparison


def _format_value(metric: str, value: float | int) -> str:
    """Format a metric value for display."""
    if metric in _RATE_METRICS:
        return f"{value:.1%}"
    if metric == "avg_duration_s":
        return f"{value:.1f}s"
    if metric == "avg_tokens":
        return str(int(value))
    return str(value)


def _format_delta(metric: str, delta: float | int) -> str:
    """Format a delta value with sign prefix."""
    sign = "+" if delta >= 0 else ""
    if metric in _RATE_METRICS:
        return f"{sign}{delta:.1%}"
    if metric == "avg_duration_s":
        return f"{sign}{delta:.1f}s"
    if metric == "avg_tokens":
        return f"{sign}{int(delta)}"
    return f"{sign}{delta}"


def comparison_to_markdown(comparison: dict[str, dict]) -> str:
    """Generate a Markdown comparison table.

    Format:
    # Phase 2 Benchmark 对比报告

    | 指标 | Baseline | Enhanced | Delta | |
    |------|----------|----------|-------|---|
    | 编译率 | 60.0% | 80.0% | +20.0% | ↑ |

    Use ↑ for improved, ↓ for not improved.
    Rate metrics (compile_rate etc.) formatted as percentages.
    Duration as seconds. Tokens as integers.
    """
    lines: list[str] = []
    lines.append("# Phase 2 Benchmark 对比报告")
    lines.append("")
    lines.append("| 指标 | Baseline | Enhanced | Delta | |")
    lines.append("|------|----------|----------|-------|---|")

    for metric, data in comparison.items():
        label = _METRIC_LABELS.get(metric, metric)
        b_str = _format_value(metric, data["baseline"])
        e_str = _format_value(metric, data["enhanced"])
        d_str = _format_delta(metric, data["delta"])
        arrow = "↑" if data["improved"] else "↓"
        lines.append(f"| {label} | {b_str} | {e_str} | {d_str} | {arrow} |")

    return "\n".join(lines)
