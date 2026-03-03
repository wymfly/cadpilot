"""Tests for knowledge base expansion — verify counts and quality after adding ~13 new examples."""

from __future__ import annotations

import pytest

from backend.knowledge.examples import EXAMPLES_BY_TYPE, get_tagged_examples
from backend.knowledge.part_types import PartType


# ---------------------------------------------------------------------------
# Example counts per part type
# ---------------------------------------------------------------------------


class TestExampleCounts:
    def test_rotational_has_8(self) -> None:
        assert len(get_tagged_examples(PartType.ROTATIONAL)) >= 8

    def test_plate_has_6(self) -> None:
        assert len(get_tagged_examples(PartType.PLATE)) >= 6

    def test_bracket_has_6(self) -> None:
        assert len(get_tagged_examples(PartType.BRACKET)) >= 6

    def test_housing_has_5(self) -> None:
        assert len(get_tagged_examples(PartType.HOUSING)) >= 5

    def test_general_has_5(self) -> None:
        assert len(get_tagged_examples(PartType.GENERAL)) >= 5

    def test_gear_unchanged_at_3(self) -> None:
        assert len(get_tagged_examples(PartType.GEAR)) >= 3

    def test_total_at_least_36(self) -> None:
        seen_ids: set[int] = set()
        total = 0
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                if id(ex) not in seen_ids:
                    seen_ids.add(id(ex))
                    total += 1
        assert total >= 36, f"Expected >= 36 unique examples, got {total}"


# ---------------------------------------------------------------------------
# Quality checks
# ---------------------------------------------------------------------------


class TestExampleQuality:
    def test_all_have_features(self) -> None:
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                assert len(ex.features) > 0, (
                    f"'{ex.description}' ({pt.value}) has no feature tags"
                )

    def test_all_have_export(self) -> None:
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                assert "export" in ex.code.lower(), (
                    f"'{ex.description}' ({pt.value}) missing export call"
                )

    def test_all_have_import(self) -> None:
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                assert "import cadquery" in ex.code, (
                    f"'{ex.description}' ({pt.value}) missing 'import cadquery'"
                )

    def test_unique_descriptions(self) -> None:
        seen: set[str] = set()
        seen_ids: set[int] = set()
        for examples in EXAMPLES_BY_TYPE.values():
            for ex in examples:
                if id(ex) in seen_ids:
                    continue  # skip shared references (ROTATIONAL_STEPPED shares ROTATIONAL)
                seen_ids.add(id(ex))
                assert ex.description not in seen, (
                    f"Duplicate description: {ex.description}"
                )
                seen.add(ex.description)

    def test_all_have_output_filename_placeholder(self) -> None:
        """Every example should use ${output_filename} for the export path."""
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                assert "${output_filename}" in ex.code, (
                    f"'{ex.description}' ({pt.value}) missing ${{output_filename}} placeholder"
                )

    def test_code_is_syntactically_valid(self) -> None:
        """Every example should be valid Python (compile check)."""
        for pt, examples in EXAMPLES_BY_TYPE.items():
            for ex in examples:
                # Replace placeholder so it's valid Python
                code = ex.code.replace("${output_filename}", "output.step")
                try:
                    compile(code, f"<{ex.description}>", "exec")
                except SyntaxError as e:
                    pytest.fail(
                        f"Syntax error in '{ex.description}' ({pt.value}): {e}"
                    )
