"""Tests for SmartRefiner three-layer defense."""

import warnings
from unittest.mock import MagicMock, patch

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)

from backend.knowledge.part_types import (
    BaseBodySpec,
    BoreSpec,
    DimensionLayer,
    DrawingSpec,
    PartType,
)
from backend.core.smart_refiner import SmartRefiner


def _make_spec() -> DrawingSpec:
    return DrawingSpec(
        part_type=PartType.ROTATIONAL_STEPPED,
        description="test flange",
        views=["front_section"],
        overall_dimensions={"max_diameter": 100, "total_height": 30},
        base_body=BaseBodySpec(
            method="revolve",
            profile=[
                DimensionLayer(diameter=100, height=10, label="base"),
            ],
            bore=BoreSpec(diameter=10, through=True),
        ),
        features=[],
    )


class TestSmartRefinerGuard:
    """Test the three-layer defense logic without hitting real LLM APIs."""

    def _make_refiner(self) -> SmartRefiner:
        """Create a SmartRefiner with mocked chains (no LLM init)."""
        with patch.object(SmartRefiner, "__init__", lambda self: None):
            refiner = SmartRefiner()
            refiner.compare_chain = MagicMock()
            refiner.fix_chain = MagicMock()
            return refiner

    def test_static_fail_vl_still_runs(self):
        """Layer 1: static validation fails → VL still runs (zero-risk mode)."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": "问题1: 直径不对"}
        refiner.fix_chain.invoke.return_value = {"result": "fixed_code"}

        bad_code = "d_base = 50\n"  # should be 100
        result = refiner.refine(
            code=bad_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
        )

        refiner.compare_chain.invoke.assert_called_once()  # VL always runs
        refiner.fix_chain.invoke.assert_called_once()
        assert result == "fixed_code"

    def test_static_fail_vl_pass_returns_none(self):
        """Layer 1 fails but VL says PASS → VL is authoritative, return None."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": None}  # VL PASS

        bad_code = "d_base = 50\n"  # static check fails, but VL says it's fine
        result = refiner.refine(
            code=bad_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
        )

        refiner.compare_chain.invoke.assert_called_once()
        refiner.fix_chain.invoke.assert_not_called()  # VL PASS → no fix needed
        assert result is None

    def test_static_fail_vl_fail_augments_instructions(self):
        """Layer 1 fails AND VL finds issues → fix instructions contain both."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": "问题1: 孔数不对"}
        refiner.fix_chain.invoke.return_value = {"result": "fixed_code"}

        bad_code = "d_base = 50\n"
        refiner.refine(
            code=bad_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
        )

        call_kwargs = refiner.fix_chain.invoke.call_args[0][0]
        assert "问题1: 孔数不对" in call_kwargs["fix_instructions"]
        assert "静态检查补充" in call_kwargs["fix_instructions"]

    def test_correct_code_reaches_vl(self):
        """Layers 1-2 pass → VL comparison is reached."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": None}  # VL PASS

        good_code = "d_base = 100\nh_base = 10\nd_bore = 10\ntotal_height = 30\n"
        result = refiner.refine(
            code=good_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
        )

        refiner.compare_chain.invoke.assert_called_once()
        refiner.fix_chain.invoke.assert_not_called()
        assert result is None  # PASS

    def test_vl_finds_issue_triggers_fix(self):
        """VL comparison finds differences → fix chain called."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": "问题1: 孔数不对"}
        refiner.fix_chain.invoke.return_value = {"result": "fixed_code_vl"}

        good_code = "d_base = 100\nh_base = 10\nd_bore = 10\ntotal_height = 30\n"
        result = refiner.refine(
            code=good_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
        )

        refiner.compare_chain.invoke.assert_called_once()
        refiner.fix_chain.invoke.assert_called_once()
        assert result == "fixed_code_vl"

    @patch("backend.core.smart_refiner._get_bbox_from_step")
    def test_bbox_fail_vl_still_runs(self, mock_bbox):
        """Layer 2: bbox validation fails → VL still runs (zero-risk mode)."""
        mock_bbox.return_value = (50.0, 50.0, 10.0)  # way off from 100×100×30

        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": "问题1: 高度不对"}
        refiner.fix_chain.invoke.return_value = {"result": "bbox_fixed"}

        good_code = "d_base = 100\nh_base = 10\nd_bore = 10\ntotal_height = 30\n"
        result = refiner.refine(
            code=good_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
            step_filepath="/fake/output.step",
        )

        refiner.compare_chain.invoke.assert_called_once()  # VL always runs
        refiner.fix_chain.invoke.assert_called_once()
        assert result == "bbox_fixed"

    @patch("backend.core.smart_refiner._get_bbox_from_step")
    def test_bbox_pass_reaches_vl(self, mock_bbox):
        """Layer 2: bbox passes → proceeds to VL."""
        mock_bbox.return_value = (100.0, 100.0, 30.0)  # matches spec

        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": None}  # VL PASS

        good_code = "d_base = 100\nh_base = 10\nd_bore = 10\ntotal_height = 30\n"
        result = refiner.refine(
            code=good_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
            step_filepath="/fake/output.step",
        )

        refiner.compare_chain.invoke.assert_called_once()
        assert result is None

    def test_no_step_filepath_skips_bbox(self):
        """No step_filepath → bbox check skipped, goes directly to VL."""
        refiner = self._make_refiner()
        refiner.compare_chain.invoke.return_value = {"result": None}

        good_code = "d_base = 100\nh_base = 10\nd_bore = 10\ntotal_height = 30\n"
        result = refiner.refine(
            code=good_code,
            original_image=MagicMock(),
            rendered_image=MagicMock(),
            drawing_spec=_make_spec(),
            step_filepath=None,
        )

        refiner.compare_chain.invoke.assert_called_once()
        assert result is None
