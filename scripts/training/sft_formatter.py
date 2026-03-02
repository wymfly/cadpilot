"""SFT data format conversion.

Two conversion paths:
1. (instruction, input, output) triples from code generation samples.
2. corrections_clean.jsonl → Qwen Chat JSONL for parameter correction SFT.

Usage (corrections → Qwen Chat):
    uv run python -m scripts.training.sft_formatter \
        --input data/training/corrections_clean.jsonl \
        --output-dir data/training/
"""
from __future__ import annotations

import argparse
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Original SFT triple format (code generation training data)
# ---------------------------------------------------------------------------

@dataclass
class SFTSample:
    """Single SFT training sample."""
    instruction: str
    input: str
    output: str
    source_id: str = ""


_DEFAULT_INSTRUCTION = (
    "Generate CadQuery Python code to create a 3D CAD model "
    "matching the following description."
)


def code_to_sft_sample(
    description: str,
    cadquery_code: str,
    source_id: str = "",
    instruction: str = _DEFAULT_INSTRUCTION,
) -> SFTSample:
    """Convert a (description, code) pair to SFT format."""
    return SFTSample(
        instruction=instruction,
        input=description,
        output=cadquery_code,
        source_id=source_id,
    )


def write_jsonl(samples: list[SFTSample], output_path: Path) -> int:
    """Write SFT samples to JSONL file. Returns count written."""
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for s in samples:
            record = {
                "instruction": s.instruction,
                "input": s.input,
                "output": s.output,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    logger.info("Wrote %d samples to %s", count, output_path)
    return count


@dataclass
class DatasetStats:
    """Quality statistics for a converted dataset."""
    total: int
    valid: int
    invalid: int
    valid_ratio: float
    avg_code_length: float


def compute_stats(samples: list[SFTSample]) -> DatasetStats:
    """Compute quality statistics for a dataset."""
    total = len(samples)
    valid = sum(1 for s in samples if s.output.strip())
    code_lengths = [len(s.output) for s in samples if s.output.strip()]
    return DatasetStats(
        total=total,
        valid=valid,
        invalid=total - valid,
        valid_ratio=valid / total if total > 0 else 0.0,
        avg_code_length=sum(code_lengths) / len(code_lengths) if code_lengths else 0.0,
    )


# ---------------------------------------------------------------------------
# Corrections → Qwen Chat format (parameter correction training data)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = (
    "你是 CAD 参数校正专家。零件类型: {part_type}。"
    "根据用户输入的规格参数，输出需要修正的字段和正确值。"
)

DEFAULT_PART_TYPE = "GENERAL"


@dataclass
class ConversionStats:
    """Statistics from a correction format conversion run."""

    total_input: int
    converted: int
    skipped: int
    train_count: int
    eval_count: int


def _extract_part_type(input_spec: dict) -> str:
    """Extract part_type from input_spec, default to GENERAL."""
    return input_spec.get("part_type", DEFAULT_PART_TYPE)


def _format_corrections(corrections: list[dict]) -> str:
    """Format corrections list into assistant response text.

    Each correction becomes a line: "field_path: corrected_value"
    """
    lines = []
    for c in corrections:
        field_path = c.get("field_path", "")
        corrected_value = c.get("corrected_value", "")
        lines.append(f"{field_path}: {corrected_value}")
    return "\n".join(lines)


def record_to_chat(record: dict) -> dict | None:
    """Convert a single correction record to Qwen Chat JSONL format.

    Returns None if the record is invalid (missing required fields or
    empty corrections).
    """
    input_spec = record.get("input_spec")
    corrections = record.get("corrections")

    if not input_spec or not corrections:
        return None

    part_type = _extract_part_type(input_spec)
    system_content = SYSTEM_PROMPT_TEMPLATE.format(part_type=part_type)
    user_content = json.dumps(input_spec, ensure_ascii=False)
    assistant_content = _format_corrections(corrections)

    if not assistant_content.strip():
        return None

    return {
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": assistant_content},
        ]
    }


def convert_corrections_file(input_path: Path) -> tuple[list[dict], int]:
    """Read corrections_clean.jsonl and convert all valid records.

    Returns (samples, skipped_count).
    """
    samples: list[dict] = []
    skipped = 0

    with open(input_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON at line %d", line_num)
                skipped += 1
                continue

            chat = record_to_chat(record)
            if chat is None:
                logger.debug(
                    "Skipping record at line %d (missing fields or empty corrections)",
                    line_num,
                )
                skipped += 1
                continue

            samples.append(chat)

    logger.info(
        "Converted %d records, skipped %d from %s",
        len(samples),
        skipped,
        input_path,
    )
    return samples, skipped


def split_train_eval(
    samples: list[dict],
    eval_ratio: float = 0.1,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    """Split samples into train/eval sets with deterministic shuffle."""
    shuffled = list(samples)
    random.seed(seed)
    random.shuffle(shuffled)

    split_idx = len(shuffled) - int(len(shuffled) * eval_ratio)
    return shuffled[:split_idx], shuffled[split_idx:]


def write_chat_jsonl(records: list[dict], output_path: Path) -> int:
    """Write chat-format records to JSONL file. Returns count written."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Wrote %d samples to %s", len(records), output_path)
    return len(records)


def run_corrections_pipeline(
    input_path: Path,
    output_dir: Path,
    eval_ratio: float = 0.1,
    seed: int = 42,
) -> ConversionStats:
    """Full corrections pipeline: read → convert → split → write."""
    samples, skipped = convert_corrections_file(input_path)

    if not samples:
        logger.warning("No valid samples found in %s", input_path)
        return ConversionStats(
            total_input=skipped,
            converted=0,
            skipped=skipped,
            train_count=0,
            eval_count=0,
        )

    train, eval_ = split_train_eval(samples, eval_ratio=eval_ratio, seed=seed)

    train_path = output_dir / "sft_train.jsonl"
    eval_path = output_dir / "sft_eval.jsonl"

    write_chat_jsonl(train, train_path)
    write_chat_jsonl(eval_, eval_path)

    total_input = len(samples) + skipped
    return ConversionStats(
        total_input=total_input,
        converted=len(samples),
        skipped=skipped,
        train_count=len(train),
        eval_count=len(eval_),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert corrections_clean.jsonl to Qwen Chat SFT format."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to corrections_clean.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/training"),
        help="Output directory for sft_train.jsonl and sft_eval.jsonl",
    )
    parser.add_argument(
        "--eval-ratio",
        type=float,
        default=0.1,
        help="Fraction of data for evaluation (default: 0.1)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic split (default: 42)",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    stats = run_corrections_pipeline(
        input_path=args.input,
        output_dir=args.output_dir,
        eval_ratio=args.eval_ratio,
        seed=args.seed,
    )
    print(
        f"Done: {stats.converted} converted, "
        f"{stats.train_count} train / {stats.eval_count} eval"
    )


if __name__ == "__main__":
    main()
