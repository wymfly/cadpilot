"""Benchmark runner — iterate over a dataset, run the pipeline, collect metrics.

Usage (CLI):
    python -m backend.benchmark.runner --dataset benchmarks/v1/

Usage (programmatic):
    runner = BenchmarkRunner()
    report = await runner.run("benchmarks/v1/")
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

from .metrics import BenchmarkMetrics, BenchmarkResult, FailureCategory, classify_failure
from .reporter import BenchmarkReporter


# ---------------------------------------------------------------------------
# Helpers — numeric extraction & comparison
# ---------------------------------------------------------------------------


def _extract_numeric_values(obj: dict | list, prefix: str = "") -> dict[str, float]:
    """Recursively extract numeric values from nested dict/list structures.

    Skips boolean values and keys containing 'tolerance'.
    """
    result: dict[str, float] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if "tolerance" in key:
                continue
            if isinstance(value, bool):
                continue
            elif isinstance(value, (int, float)):
                result[full_key] = float(value)
            elif isinstance(value, (dict, list)):
                result.update(_extract_numeric_values(value, full_key))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            idx_key = f"{prefix}[{i}]"
            if isinstance(item, bool):
                continue
            elif isinstance(item, (int, float)):
                result[idx_key] = float(item)
            elif isinstance(item, (dict, list)):
                result.update(_extract_numeric_values(item, idx_key))
    return result


def _compute_param_accuracy(
    expected_spec: dict,
    actual_bbox: tuple[float, float, float] | None,
) -> float:
    """Compare expected_spec numeric fields against actual STEP bbox dimensions.

    For each positive numeric value in expected_spec, check if it's within 10%
    of any actual bbox dimension.  Returns matched / total.
    """
    if actual_bbox is None:
        return 0.0

    numeric_vals = _extract_numeric_values(expected_spec)
    dimension_vals = {k: v for k, v in numeric_vals.items() if v > 0}
    if not dimension_vals:
        return 0.0

    actual_dims = [d for d in actual_bbox if d > 0]
    if not actual_dims:
        return 0.0

    matched = 0
    for _key, expected_val in dimension_vals.items():
        for actual_val in actual_dims:
            if abs(actual_val - expected_val) / expected_val <= 0.10:
                matched += 1
                break

    return matched / len(dimension_vals)


def _check_bbox_match(
    expected_bbox: dict,
    actual_bbox: tuple[float, float, float] | None,
    default_tolerance_pct: float = 15.0,
) -> bool:
    """Check if actual STEP bbox matches expected bbox within tolerance.

    Uses ``tolerance_pct`` from *expected_bbox* if present, else *default_tolerance_pct*.
    """
    if actual_bbox is None or not expected_bbox:
        return False

    tol = expected_bbox.get("tolerance_pct", default_tolerance_pct) / 100.0
    pairs = [
        (expected_bbox.get("xlen", 0), actual_bbox[0]),
        (expected_bbox.get("ylen", 0), actual_bbox[1]),
        (expected_bbox.get("zlen", 0), actual_bbox[2]),
    ]

    checked = 0
    for exp, act in pairs:
        if exp <= 0:
            continue
        checked += 1
        if abs(act - exp) / exp > tol:
            return False
    # At least one positive dimension must have been checked
    return checked > 0


def _classify_exception(exc: Exception) -> FailureCategory:
    """Map a pipeline exception to a FailureCategory."""
    msg = str(exc).lower()
    if any(kw in msg for kw in ("compile", "syntax", "execution", "sandbox")):
        return classify_failure(compile_error=str(exc)) or FailureCategory.CODE_EXECUTION
    if "type" in msg and ("mismatch" in msg or "recognition" in msg):
        return classify_failure(type_mismatch=True) or FailureCategory.TYPE_RECOGNITION
    if any(kw in msg for kw in ("template", "not found", "structural")):
        return classify_failure(structural_error=str(exc)) or FailureCategory.STRUCTURAL_ERROR
    return classify_failure(compile_error=str(exc)) or FailureCategory.CODE_EXECUTION


# ---------------------------------------------------------------------------
# Benchmark case (loaded from JSON)
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkCase:
    """A single benchmark test case loaded from the dataset."""

    case_id: str
    input_type: str = "drawing"
    drawing_path: str = ""
    input_text: str = ""
    template_name: str = ""
    params: dict = field(default_factory=dict)
    intent: dict = field(default_factory=dict)
    expected_spec: dict = field(default_factory=dict)
    expected_bbox: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str) -> BenchmarkCase:
        with open(path) as f:
            data = json.load(f)
        base_dir = str(Path(path).parent)
        drawing_path = data.get("drawing_path", "")
        if drawing_path and not Path(drawing_path).is_absolute():
            drawing_path = str(Path(base_dir) / drawing_path)
        return cls(
            case_id=data["case_id"],
            input_type=data.get("input_type", "drawing"),
            drawing_path=drawing_path,
            input_text=data.get("input_text", ""),
            template_name=data.get("template_name", ""),
            params=data.get("params", {}),
            intent=data.get("intent", {}),
            expected_spec=data.get("expected_spec", {}),
            expected_bbox=data.get("expected_bbox", {}),
        )


# ---------------------------------------------------------------------------
# Report container
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkReport:
    """Full benchmark run report."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    dataset: str = ""
    metrics: BenchmarkMetrics = field(default_factory=BenchmarkMetrics)
    results: list[BenchmarkResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchmarkRunner:
    """Load dataset, run pipeline on each case, aggregate results."""

    def __init__(self, reports_dir: str = "benchmark_reports") -> None:
        self._reports_dir = Path(reports_dir)
        self._reporter = BenchmarkReporter()

    def load_cases(self, dataset_dir: str) -> list[BenchmarkCase]:
        """Load all case JSON files from *dataset_dir*."""
        dpath = Path(dataset_dir)
        if not dpath.exists():
            raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
        case_files = sorted(dpath.glob("case_*.json"))
        return [BenchmarkCase.from_json(str(f)) for f in case_files]

    async def run(
        self,
        dataset_dir: str,
        *,
        workers: int = 4,  # TODO: implement concurrent execution with asyncio.Semaphore
    ) -> BenchmarkReport:
        """Run the full benchmark and return a report."""
        cases = self.load_cases(dataset_dir)
        dataset_name = Path(dataset_dir).name

        results: list[BenchmarkResult] = []
        for case in cases:
            result = await self._run_single(case)
            results.append(result)

        metrics = BenchmarkMetrics.from_results(results)
        report = BenchmarkReport(
            dataset=dataset_name,
            metrics=metrics,
            results=results,
        )

        self._save_report(report)
        return report

    async def run_streaming(
        self,
        dataset_dir: str,
        *,
        workers: int = 4,
    ) -> AsyncGenerator[dict, None]:
        """Run benchmark yielding progress events for SSE streaming."""
        cases = self.load_cases(dataset_dir)
        dataset_name = Path(dataset_dir).name
        total = len(cases)

        yield {"event": "started", "total": total, "dataset": dataset_name}

        results: list[BenchmarkResult] = []
        for i, case in enumerate(cases):
            yield {"event": "progress", "current": i + 1, "total": total, "case_id": case.case_id}
            result = await self._run_single(case)
            results.append(result)
            yield {
                "event": "case_complete",
                "case_id": case.case_id,
                "compiled": result.compiled,
                "param_accuracy": result.param_accuracy,
            }

        metrics = BenchmarkMetrics.from_results(results)
        report = BenchmarkReport(dataset=dataset_name, metrics=metrics, results=results)
        self._save_report(report)

        yield {
            "event": "complete",
            "run_id": report.run_id,
            "metrics": metrics.model_dump(),
        }

    async def _run_single(self, case: BenchmarkCase) -> BenchmarkResult:
        """Run the pipeline on a single case and collect metrics."""
        start = time.monotonic()

        compiled = False
        type_correct = False
        param_accuracy = 0.0
        bbox_match = False
        failure_cat: FailureCategory | None = None
        error_detail = ""
        tokens_used = 0
        step_path = ""

        try:
            with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
                step_path = tmp.name

            if case.input_type == "text":
                await self._run_text_case(case, step_path)
            else:
                await self._run_drawing_case(case, step_path)

            # Pipeline completed — validate generated STEP geometry
            from backend.core.validators import validate_step_geometry

            geo = await asyncio.to_thread(validate_step_geometry, step_path)

            if not geo.is_valid:
                failure_cat = classify_failure(
                    compile_error=geo.error or "Invalid geometry",
                )
                error_detail = geo.error or "Invalid geometry"
            else:
                compiled = True
                # TODO: compare against pipeline-inferred part_type once
                # the pipeline exposes it.  For now, mark as correct when
                # the STEP geometry is valid (placeholder metric).
                type_correct = compiled
                param_accuracy = _compute_param_accuracy(case.expected_spec, geo.bbox)
                bbox_match = _check_bbox_match(case.expected_bbox, geo.bbox)

                if not bbox_match and param_accuracy < 0.5:
                    failure_cat = classify_failure(
                        param_error="Dimension deviation beyond tolerance",
                    )

        except Exception as e:
            error_detail = str(e)
            failure_cat = _classify_exception(e)

        finally:
            if step_path:
                try:
                    Path(step_path).unlink(missing_ok=True)
                except Exception:
                    pass

        duration = time.monotonic() - start

        return BenchmarkResult(
            case_id=case.case_id,
            compiled=compiled,
            type_correct=type_correct,
            param_accuracy=param_accuracy,
            bbox_match=bbox_match,
            duration_s=duration,
            tokens_used=tokens_used,
            failure_category=failure_cat,
            error_detail=error_detail,
        )

    async def _run_drawing_case(
        self, case: BenchmarkCase, step_path: str,
    ) -> str | None:
        """Run drawing *generation-only* benchmark.

        Uses the case's expected_spec as a ground-truth DrawingSpec so the
        benchmark isolates code generation quality from drawing analysis.
        For end-to-end benchmarks (including VL analysis), a separate
        pipeline entry point is needed.
        """
        from backend.knowledge.part_types import DrawingSpec
        from backend.pipeline.pipeline import generate_step_from_spec

        spec = DrawingSpec(**case.expected_spec)
        code = await asyncio.to_thread(
            generate_step_from_spec,
            case.drawing_path,
            spec,
            step_path,
        )
        if code is None:
            raise RuntimeError("Pipeline returned None — code generation failed")
        return code

    async def _run_text_case(self, case: BenchmarkCase, step_path: str) -> None:
        """Run text pipeline: SpecCompiler.compile()."""
        from backend.core.spec_compiler import SpecCompiler

        compiler = SpecCompiler()
        await asyncio.to_thread(
            lambda: compiler.compile(
                matched_template=case.template_name or None,
                params=case.params,
                output_path=step_path,
                input_text=case.input_text,
                intent=case.intent or None,
            )
        )

    def _save_report(self, report: BenchmarkReport) -> None:
        """Persist report to disk as JSON + Markdown."""
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        base = self._reports_dir / report.run_id

        self._reporter.to_json(
            report.metrics, report.results, str(base.with_suffix(".json")),
            dataset=report.dataset,
        )

        md = self._reporter.to_markdown(report.metrics, report.results, dataset=report.dataset)
        base.with_suffix(".md").write_text(md)

    def list_reports(self) -> list[dict]:
        """List all saved reports (for history endpoint)."""
        if not self._reports_dir.exists():
            return []
        reports = []
        for f in sorted(self._reports_dir.glob("*.json"), reverse=True):
            with open(f) as fh:
                data = json.load(fh)
            reports.append({
                "run_id": f.stem,
                "dataset": data.get("dataset", ""),
                "timestamp": data.get("timestamp", ""),
                "total_cases": data.get("total_cases", 0),
                "metrics": data.get("metrics", {}),
            })
        return reports

    def get_report(self, run_id: str) -> dict | None:
        """Load a specific report by run_id."""
        path = self._reports_dir / f"{run_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run benchmark evaluation")
    parser.add_argument("--dataset", required=True, help="Path to dataset directory")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    async def _main() -> None:
        runner = BenchmarkRunner()
        report = await runner.run(args.dataset, workers=args.workers)
        print(f"Benchmark complete: {report.run_id}")
        print(f"  Compile rate: {report.metrics.compile_rate:.1%}")
        print(f"  Type accuracy: {report.metrics.type_accuracy:.1%}")
        print(f"  Param accuracy (P50): {report.metrics.param_accuracy_p50:.1%}")
        print(f"  BBox match rate: {report.metrics.bbox_match_rate:.1%}")

    asyncio.run(_main())
