"""Tests for benchmark comparison report generation."""

from __future__ import annotations

import pytest

from backend.benchmark.metrics import BenchmarkMetrics


class TestBenchmarkComparator:
    def test_compute_delta(self) -> None:
        from backend.benchmark.comparator import compute_comparison

        baseline = BenchmarkMetrics(
            compile_rate=0.60,
            type_accuracy=0.40,
            param_accuracy_p50=0.50,
            bbox_match_rate=0.40,
            avg_duration_s=15.0,
            avg_tokens=1000,
        )
        enhanced = BenchmarkMetrics(
            compile_rate=0.80,
            type_accuracy=0.60,
            param_accuracy_p50=0.70,
            bbox_match_rate=0.60,
            avg_duration_s=25.0,
            avg_tokens=3000,
        )
        report = compute_comparison(baseline, enhanced)
        assert report["compile_rate"]["delta"] == pytest.approx(0.20)
        assert report["compile_rate"]["improved"] is True
        assert report["avg_duration_s"]["improved"] is False  # higher duration is worse
        assert report["avg_tokens"]["improved"] is False  # more tokens is worse

    def test_all_improved(self) -> None:
        from backend.benchmark.comparator import compute_comparison

        baseline = BenchmarkMetrics(
            compile_rate=0.50,
            type_accuracy=0.30,
            param_accuracy_p50=0.40,
            bbox_match_rate=0.30,
            avg_duration_s=20.0,
            avg_tokens=2000,
        )
        enhanced = BenchmarkMetrics(
            compile_rate=0.90,
            type_accuracy=0.80,
            param_accuracy_p50=0.85,
            bbox_match_rate=0.80,
            avg_duration_s=10.0,
            avg_tokens=1500,
        )
        report = compute_comparison(baseline, enhanced)
        for key in report:
            assert report[key]["improved"] is True

    def test_identical_metrics(self) -> None:
        from backend.benchmark.comparator import compute_comparison

        m = BenchmarkMetrics(
            compile_rate=0.50,
            type_accuracy=0.50,
            param_accuracy_p50=0.50,
            bbox_match_rate=0.50,
            avg_duration_s=10.0,
            avg_tokens=500,
        )
        report = compute_comparison(m, m)
        for key in report:
            assert report[key]["delta"] == pytest.approx(0.0)
            assert report[key]["improved"] is False  # no change = not improved

    def test_markdown_output(self) -> None:
        from backend.benchmark.comparator import comparison_to_markdown

        comparison = {
            "compile_rate": {
                "baseline": 0.6,
                "enhanced": 0.8,
                "delta": 0.2,
                "improved": True,
            },
            "type_accuracy": {
                "baseline": 0.4,
                "enhanced": 0.6,
                "delta": 0.2,
                "improved": True,
            },
            "param_accuracy_p50": {
                "baseline": 0.5,
                "enhanced": 0.7,
                "delta": 0.2,
                "improved": True,
            },
            "bbox_match_rate": {
                "baseline": 0.4,
                "enhanced": 0.6,
                "delta": 0.2,
                "improved": True,
            },
            "avg_duration_s": {
                "baseline": 15.0,
                "enhanced": 25.0,
                "delta": 10.0,
                "improved": False,
            },
            "avg_tokens": {
                "baseline": 1000,
                "enhanced": 3000,
                "delta": 2000,
                "improved": False,
            },
        }
        md = comparison_to_markdown(comparison)
        assert "Phase 2" in md
        assert "↑" in md
        assert "↓" in md
        assert "编译率" in md or "compile_rate" in md

    def test_markdown_contains_all_metrics(self) -> None:
        from backend.benchmark.comparator import compute_comparison, comparison_to_markdown

        baseline = BenchmarkMetrics(
            compile_rate=0.60,
            type_accuracy=0.40,
            param_accuracy_p50=0.50,
            bbox_match_rate=0.40,
            avg_duration_s=15.0,
            avg_tokens=1000,
        )
        enhanced = BenchmarkMetrics(
            compile_rate=0.80,
            type_accuracy=0.60,
            param_accuracy_p50=0.70,
            bbox_match_rate=0.60,
            avg_duration_s=25.0,
            avg_tokens=3000,
        )
        comparison = compute_comparison(baseline, enhanced)
        md = comparison_to_markdown(comparison)
        # Should contain all 6 metric rows
        assert md.count("|") > 20  # at least header + 6 rows
