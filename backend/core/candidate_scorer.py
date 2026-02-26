"""Candidate scoring for Best-of-N code generation.

Score breakdown (total 100):
- Compiled successfully: 50 points
- Volume within tolerance: 20 points
- Bounding box within tolerance: 20 points
- Topology valid: 10 points

A candidate that fails compilation always gets 0.
"""

from __future__ import annotations


def score_candidate(
    *,
    compiled: bool,
    volume_ok: bool = False,
    bbox_ok: bool = False,
    topology_ok: bool = False,
) -> int:
    """Score a single code candidate. Returns 0-100."""
    if not compiled:
        return 0

    score = 50
    if volume_ok:
        score += 20
    if bbox_ok:
        score += 20
    if topology_ok:
        score += 10
    return score


def select_best(candidates: list[dict]) -> dict | None:
    """Select highest-scoring candidate.

    Each item has ``{"code": str, "score": int, ...}``.
    Returns *None* if the list is empty.
    """
    if not candidates:
        return None
    return max(candidates, key=lambda c: c["score"])
