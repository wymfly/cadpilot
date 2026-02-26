"""Tests for candidate scoring and Best-of-N selection."""

from __future__ import annotations

from backend.core.candidate_scorer import score_candidate, select_best


# ---------------------------------------------------------------------------
# TestCandidateScorer
# ---------------------------------------------------------------------------


class TestCandidateScorer:
    def test_compiled_candidate_scores_50(self) -> None:
        """compiled=True, rest False → 50."""
        assert score_candidate(compiled=True) == 50

    def test_all_pass_scores_100(self) -> None:
        """All True → 100."""
        assert score_candidate(
            compiled=True, volume_ok=True, bbox_ok=True, topology_ok=True
        ) == 100

    def test_uncompiled_scores_zero(self) -> None:
        """compiled=False, rest True → 0."""
        assert score_candidate(
            compiled=False, volume_ok=True, bbox_ok=True, topology_ok=True
        ) == 0

    def test_partial_scores(self) -> None:
        """compiled=True, volume_ok=True, rest False → 70."""
        assert score_candidate(compiled=True, volume_ok=True) == 70


# ---------------------------------------------------------------------------
# TestSelectBestCandidate
# ---------------------------------------------------------------------------


class TestSelectBestCandidate:
    def test_selects_highest_score(self) -> None:
        """List of 3 candidates → returns highest."""
        candidates = [
            {"code": "a", "score": 50},
            {"code": "b", "score": 100},
            {"code": "c", "score": 70},
        ]
        best = select_best(candidates)
        assert best is not None
        assert best["code"] == "b"
        assert best["score"] == 100

    def test_empty_candidates_returns_none(self) -> None:
        """Empty list → None."""
        assert select_best([]) is None

    def test_single_candidate(self) -> None:
        """Single item → returns it."""
        candidates = [{"code": "only", "score": 50}]
        best = select_best(candidates)
        assert best is not None
        assert best["code"] == "only"
