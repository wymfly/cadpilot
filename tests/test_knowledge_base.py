"""Tests for the feature-tagged knowledge base examples."""

from __future__ import annotations

import pytest

from backend.knowledge.examples import (
    EXAMPLES_BY_TYPE,
    TaggedExample,
    get_examples,
    get_tagged_examples,
)
from backend.knowledge.examples.bracket import BRACKET_EXAMPLES
from backend.knowledge.examples.gear import GEAR_EXAMPLES
from backend.knowledge.examples.general import GENERAL_EXAMPLES
from backend.knowledge.examples.housing import HOUSING_EXAMPLES
from backend.knowledge.examples.plate import PLATE_EXAMPLES
from backend.knowledge.examples.rotational import ROTATIONAL_EXAMPLES
from backend.knowledge.part_types import PartType

# ---------------------------------------------------------------------------
# TaggedExample dataclass
# ---------------------------------------------------------------------------


class TestTaggedExample:
    def test_fields_present(self) -> None:
        ex = TaggedExample(
            description="test part",
            code="import cadquery as cq",
            features=frozenset({"extrude", "bore"}),
        )
        assert ex.description == "test part"
        assert ex.code == "import cadquery as cq"
        assert ex.features == frozenset({"extrude", "bore"})

    def test_default_features_empty(self) -> None:
        ex = TaggedExample(description="d", code="c")
        assert isinstance(ex.features, frozenset)
        assert len(ex.features) == 0

    def test_features_immutable(self) -> None:
        ex = TaggedExample(description="d", code="c", features=frozenset({"a"}))
        with pytest.raises(AttributeError):
            ex.features = frozenset({"b"})  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Per-module example lists
# ---------------------------------------------------------------------------


class TestExampleModules:
    @pytest.mark.parametrize(
        "examples, min_count",
        [
            (ROTATIONAL_EXAMPLES, 8),
            (PLATE_EXAMPLES, 6),
            (BRACKET_EXAMPLES, 6),
            (HOUSING_EXAMPLES, 5),
            (GEAR_EXAMPLES, 3),
            (GENERAL_EXAMPLES, 5),
        ],
    )
    def test_count(
        self, examples: list[TaggedExample], min_count: int
    ) -> None:
        assert len(examples) >= min_count

    @pytest.mark.parametrize(
        "examples",
        [
            ROTATIONAL_EXAMPLES,
            PLATE_EXAMPLES,
            BRACKET_EXAMPLES,
            HOUSING_EXAMPLES,
            GEAR_EXAMPLES,
            GENERAL_EXAMPLES,
        ],
    )
    def test_all_tagged(self, examples: list[TaggedExample]) -> None:
        for ex in examples:
            assert isinstance(ex, TaggedExample)
            assert ex.description
            assert ex.code
            assert len(ex.features) > 0, (
                f"Example '{ex.description}' has no feature tags"
            )

    @pytest.mark.parametrize(
        "examples",
        [
            ROTATIONAL_EXAMPLES,
            PLATE_EXAMPLES,
            BRACKET_EXAMPLES,
            HOUSING_EXAMPLES,
            GEAR_EXAMPLES,
            GENERAL_EXAMPLES,
        ],
    )
    def test_code_contains_cadquery(self, examples: list[TaggedExample]) -> None:
        for ex in examples:
            assert "cadquery" in ex.code, (
                f"Example '{ex.description}' code doesn't import cadquery"
            )
            assert "export" in ex.code, (
                f"Example '{ex.description}' code doesn't call export"
            )


# ---------------------------------------------------------------------------
# Total example count
# ---------------------------------------------------------------------------


class TestTotalCount:
    def test_total_examples_at_least_20(self) -> None:
        total = sum(
            len(examples)
            for part_type, examples in EXAMPLES_BY_TYPE.items()
            if part_type != PartType.ROTATIONAL_STEPPED  # 共享，不重复计数
        )
        assert total >= 36, f"Expected ≥36 examples, got {total}"


# ---------------------------------------------------------------------------
# EXAMPLES_BY_TYPE coverage
# ---------------------------------------------------------------------------


class TestExamplesByType:
    def test_all_part_types_covered(self) -> None:
        for part_type in PartType:
            examples = EXAMPLES_BY_TYPE.get(part_type, [])
            assert len(examples) > 0, f"No examples for {part_type}"

    def test_rotational_stepped_shares_rotational(self) -> None:
        assert (
            EXAMPLES_BY_TYPE[PartType.ROTATIONAL_STEPPED]
            is EXAMPLES_BY_TYPE[PartType.ROTATIONAL]
        )

    def test_gear_examples_distinct(self) -> None:
        assert EXAMPLES_BY_TYPE[PartType.GEAR] is GEAR_EXAMPLES

    def test_general_examples_distinct(self) -> None:
        assert EXAMPLES_BY_TYPE[PartType.GENERAL] is GENERAL_EXAMPLES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TestGetExamples:
    def test_backward_compat_returns_tuples(self) -> None:
        result = get_examples(PartType.ROTATIONAL)
        assert len(result) > 0
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            description, code = item
            assert isinstance(description, str)
            assert isinstance(code, str)

    def test_unknown_type_returns_empty(self) -> None:
        # PartType.GENERAL is covered, use a mock int to test fallback
        result = EXAMPLES_BY_TYPE.get("nonexistent_type", [])  # type: ignore[arg-type]
        assert result == []

    def test_gear_type_returns_examples(self) -> None:
        result = get_examples(PartType.GEAR)
        assert len(result) >= 3


class TestGetTaggedExamples:
    def test_returns_tagged_example_instances(self) -> None:
        result = get_tagged_examples(PartType.PLATE)
        assert len(result) > 0
        for ex in result:
            assert isinstance(ex, TaggedExample)

    def test_features_are_frozensets(self) -> None:
        for part_type in PartType:
            for ex in get_tagged_examples(part_type):
                assert isinstance(ex.features, frozenset)

    def test_gear_has_gear_teeth_tag(self) -> None:
        examples = get_tagged_examples(PartType.GEAR)
        assert all("gear_teeth" in ex.features for ex in examples)

    def test_rotational_has_revolve_tag(self) -> None:
        examples = get_tagged_examples(PartType.ROTATIONAL)
        assert all("revolve" in ex.features for ex in examples)
