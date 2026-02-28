"""Field-level correction tracking for DrawingSpec HITL data flywheel.

Compares original (VL-generated) and confirmed (user-reviewed) DrawingSpec
dicts, produces field-level correction records, and persists them to JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CORRECTIONS_DIR = Path(__file__).parent.parent / "data" / "corrections"


def compute_corrections(
    original: dict[str, Any],
    confirmed: dict[str, Any],
    job_id: str,
) -> list[dict[str, Any]]:
    """Compare original and confirmed DrawingSpec, return field-level diffs."""
    corrections: list[dict[str, Any]] = []
    _diff_recursive(original, confirmed, "", corrections, job_id)
    return corrections


def _diff_recursive(
    orig: Any,
    conf: Any,
    path: str,
    corrections: list[dict[str, Any]],
    job_id: str,
) -> None:
    """Recursively diff two values, appending corrections for differences."""
    if isinstance(orig, dict) and isinstance(conf, dict):
        all_keys = set(list(orig.keys()) + list(conf.keys()))
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            _diff_recursive(
                orig.get(key), conf.get(key),
                child_path, corrections, job_id,
            )
    elif isinstance(orig, list) and isinstance(conf, list):
        max_len = max(len(orig), len(conf))
        for i in range(max_len):
            child_path = f"{path}[{i}]"
            orig_item = orig[i] if i < len(orig) else None
            conf_item = conf[i] if i < len(conf) else None
            _diff_recursive(orig_item, conf_item, child_path, corrections, job_id)
    elif orig != conf:
        corrections.append({
            "job_id": job_id,
            "field_path": path,
            "original_value": str(orig),
            "corrected_value": str(conf),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def persist_corrections(job_id: str, corrections: list[dict[str, Any]]) -> Path:
    """Persist corrections to JSON file. MANDATORY — not optional."""
    CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = CORRECTIONS_DIR / f"{job_id}.json"
    path.write_text(json.dumps(corrections, ensure_ascii=False, indent=2))
    logger.info(f"Persisted {len(corrections)} corrections to {path}")
    return path


def load_corrections(job_id: str) -> list[dict[str, Any]] | None:
    """Load corrections from JSON file. Returns None if not found or corrupted."""
    path = CORRECTIONS_DIR / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Corrupt corrections file for job %s: %s", job_id, exc)
        return None
