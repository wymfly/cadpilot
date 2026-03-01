"""Tests for TokenTracker — per-stage LLM usage monitoring."""

from __future__ import annotations

import json
from pathlib import Path

from backend.infra.token_tracker import TokenTracker


def test_token_tracker_records_usage():
    tracker = TokenTracker()
    tracker.record("stage1_analysis", input_tokens=500, output_tokens=200, duration_s=1.5)
    tracker.record("stage2_codegen", input_tokens=1000, output_tokens=800, duration_s=3.2)
    stats = tracker.get_stats()
    assert stats["total_input_tokens"] == 1500
    assert stats["total_output_tokens"] == 1000
    assert len(stats["stages"]) == 2


def test_token_tracker_export_json(tmp_path: Path):
    tracker = TokenTracker()
    tracker.record("test", input_tokens=100, output_tokens=50, duration_s=0.5)
    path = str(tmp_path / "stats.json")
    tracker.export_json(path)
    with open(path) as f:
        data = json.load(f)
    assert data["total_input_tokens"] == 100
    assert data["total_output_tokens"] == 50
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "test"


def test_empty_tracker():
    tracker = TokenTracker()
    stats = tracker.get_stats()
    assert stats["total_input_tokens"] == 0
    assert stats["total_output_tokens"] == 0
    assert stats["total_duration_s"] == 0.0
    assert len(stats["stages"]) == 0


def test_total_duration_is_sum():
    tracker = TokenTracker()
    tracker.record("a", input_tokens=10, output_tokens=5, duration_s=1.0)
    tracker.record("b", input_tokens=20, output_tokens=10, duration_s=2.0)
    stats = tracker.get_stats()
    assert stats["total_duration_s"] == 3.0


def test_wall_time_is_positive():
    tracker = TokenTracker()
    tracker.record("x", input_tokens=1, output_tokens=1, duration_s=0.1)
    stats = tracker.get_stats()
    assert stats["wall_time_s"] > 0


def test_token_stats_in_graph_state():
    """token_stats field exists in CadJobState."""
    import typing

    from backend.graph.state import CadJobState

    hints = typing.get_type_hints(CadJobState)
    assert "token_stats" in hints
