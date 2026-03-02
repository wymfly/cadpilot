"""Tests for scripts.training.sft_formatter — corrections → Qwen Chat JSONL."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.training.sft_formatter import (
    ConversionStats,
    convert_corrections_file,
    record_to_chat,
    run_corrections_pipeline,
    split_train_eval,
    write_chat_jsonl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_record(
    job_id: str = "job-001",
    part_type: str = "ROTATIONAL",
    diameter: float = 50,
    height: float = 100,
    corrections: list[dict] | None = None,
) -> dict:
    """Create a sample correction record."""
    if corrections is None:
        corrections = [
            {"field_path": "overall_dimensions.diameter", "corrected_value": "55"},
            {"field_path": "base_body.height", "corrected_value": "110"},
        ]
    return {
        "job_id": job_id,
        "input_spec": {
            "part_type": part_type,
            "diameter": diameter,
            "height": height,
        },
        "corrections": corrections,
        "timestamp": "2026-03-01T10:00:00Z",
    }


@pytest.fixture
def sample_record() -> dict:
    return _make_record()


@pytest.fixture
def corrections_file(tmp_path: Path) -> Path:
    """Write a multi-record corrections_clean.jsonl."""
    path = tmp_path / "corrections_clean.jsonl"
    records = [
        _make_record(job_id=f"job-{i:03d}", diameter=50 + i)
        for i in range(20)
    ]
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


# ---------------------------------------------------------------------------
# record_to_chat
# ---------------------------------------------------------------------------

class TestRecordToChat:
    def test_basic_conversion(self, sample_record: dict) -> None:
        result = record_to_chat(sample_record)
        assert result is not None
        msgs = result["messages"]
        assert len(msgs) == 3
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"

    def test_system_prompt_contains_part_type(self, sample_record: dict) -> None:
        result = record_to_chat(sample_record)
        assert result is not None
        system_msg = result["messages"][0]["content"]
        assert "ROTATIONAL" in system_msg

    def test_user_message_is_json(self, sample_record: dict) -> None:
        result = record_to_chat(sample_record)
        assert result is not None
        user_content = result["messages"][1]["content"]
        parsed = json.loads(user_content)
        assert parsed["part_type"] == "ROTATIONAL"
        assert parsed["diameter"] == 50

    def test_assistant_message_format(self, sample_record: dict) -> None:
        result = record_to_chat(sample_record)
        assert result is not None
        assistant_content = result["messages"][2]["content"]
        lines = assistant_content.strip().split("\n")
        assert len(lines) == 2
        assert "overall_dimensions.diameter: 55" in lines[0]
        assert "base_body.height: 110" in lines[1]

    def test_missing_part_type_defaults_to_general(self) -> None:
        record = _make_record()
        del record["input_spec"]["part_type"]
        result = record_to_chat(record)
        assert result is not None
        assert "GENERAL" in result["messages"][0]["content"]

    def test_missing_input_spec_returns_none(self) -> None:
        record = _make_record()
        del record["input_spec"]
        assert record_to_chat(record) is None

    def test_missing_corrections_returns_none(self) -> None:
        record = _make_record()
        del record["corrections"]
        assert record_to_chat(record) is None

    def test_empty_corrections_returns_none(self) -> None:
        record = _make_record(corrections=[])
        assert record_to_chat(record) is None


# ---------------------------------------------------------------------------
# convert_corrections_file
# ---------------------------------------------------------------------------

class TestConvertFile:
    def test_converts_valid_file(self, corrections_file: Path) -> None:
        samples, skipped = convert_corrections_file(corrections_file)
        assert len(samples) == 20
        assert skipped == 0

    def test_skips_invalid_json_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "mixed.jsonl"
        good = json.dumps(_make_record())
        with open(path, "w") as f:
            f.write(good + "\n")
            f.write("NOT VALID JSON\n")
            f.write(good + "\n")
        samples, skipped = convert_corrections_file(path)
        assert len(samples) == 2
        assert skipped == 1

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "sparse.jsonl"
        good = json.dumps(_make_record())
        with open(path, "w") as f:
            f.write("\n")
            f.write(good + "\n")
            f.write("\n")
        samples, skipped = convert_corrections_file(path)
        assert len(samples) == 1


# ---------------------------------------------------------------------------
# split_train_eval
# ---------------------------------------------------------------------------

class TestSplitTrainEval:
    def test_90_10_split(self) -> None:
        samples = [{"id": i} for i in range(100)]
        train, eval_ = split_train_eval(samples, eval_ratio=0.1, seed=42)
        assert len(train) == 90
        assert len(eval_) == 10

    def test_deterministic(self) -> None:
        samples = [{"id": i} for i in range(50)]
        train1, eval1 = split_train_eval(samples, seed=42)
        train2, eval2 = split_train_eval(samples, seed=42)
        assert train1 == train2
        assert eval1 == eval2

    def test_different_seed_gives_different_split(self) -> None:
        samples = [{"id": i} for i in range(50)]
        train1, _ = split_train_eval(samples, seed=42)
        train2, _ = split_train_eval(samples, seed=99)
        assert train1 != train2

    def test_small_dataset(self) -> None:
        samples = [{"id": 0}]
        train, eval_ = split_train_eval(samples, eval_ratio=0.1, seed=42)
        assert len(train) + len(eval_) == 1

    def test_empty_dataset(self) -> None:
        train, eval_ = split_train_eval([], eval_ratio=0.1, seed=42)
        assert train == []
        assert eval_ == []


# ---------------------------------------------------------------------------
# write_chat_jsonl
# ---------------------------------------------------------------------------

class TestWriteJsonl:
    def test_writes_valid_jsonl(self, tmp_path: Path) -> None:
        records = [
            record_to_chat(_make_record(job_id=f"job-{i}"))
            for i in range(5)
        ]
        out = tmp_path / "output.jsonl"
        count = write_chat_jsonl(records, out)
        assert count == 5
        with open(out) as f:
            lines = f.readlines()
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert "messages" in parsed

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir" / "output.jsonl"
        write_chat_jsonl([{"messages": []}], out)
        assert out.exists()


# ---------------------------------------------------------------------------
# run_corrections_pipeline (end-to-end)
# ---------------------------------------------------------------------------

class TestRun:
    def test_full_pipeline(self, corrections_file: Path, tmp_path: Path) -> None:
        output_dir = tmp_path / "output"
        stats = run_corrections_pipeline(corrections_file, output_dir, eval_ratio=0.1, seed=42)

        assert isinstance(stats, ConversionStats)
        assert stats.converted == 20
        assert stats.train_count == 18
        assert stats.eval_count == 2
        assert stats.train_count + stats.eval_count == stats.converted

        train_path = output_dir / "sft_train.jsonl"
        eval_path = output_dir / "sft_eval.jsonl"
        assert train_path.exists()
        assert eval_path.exists()

        with open(train_path) as f:
            train_lines = f.readlines()
        assert len(train_lines) == 18

    def test_empty_input(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        output_dir = tmp_path / "output"
        stats = run_corrections_pipeline(empty, output_dir)
        assert stats.converted == 0
        assert stats.train_count == 0
        assert stats.eval_count == 0
