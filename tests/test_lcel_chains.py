"""Tests for LCEL chain builders in backend.graph.chains."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeChatModel:
    """Minimal fake that supports ``with_retry()`` and ``|`` (pipe) operator.

    MagicMock doesn't implement the Runnable protocol, so the ``|``
    operator in ``prompt | llm | parser`` breaks.  This class returns
    a proper ``RunnableLambda`` from ``with_retry()`` that the pipe
    operator can compose.
    """

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.retry_kwargs: dict | None = None

    def with_retry(self, **kwargs) -> RunnableLambda:
        self.retry_kwargs = kwargs
        return RunnableLambda(
            lambda _input: AIMessage(content=self._response_text)
        )

    def invoke(self, input):
        return AIMessage(content=self._response_text)


def _setup_mock_model(mock_get_model, response_text: str) -> _FakeChatModel:
    """Wire up get_model_for_role → ChatModelParameters → _FakeChatModel."""
    fake_llm = _FakeChatModel(response_text)
    mock_get_model.return_value.create_chat_model.return_value = fake_llm
    return fake_llm


# Compare chain input template (all 6 required fields)
_COMPARE_INPUT = {
    "drawing_spec": '{"part_type": "rotational"}',
    "code": "cq.Workplane('XY').cylinder(10, 5)",
    "original_image_type": "png",
    "original_image_data": "base64orig",
    "rendered_image_type": "png",
    "rendered_image_data": "base64rend",
}


# ===================================================================
# Fix Chain
# ===================================================================
class TestFixChain:
    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_parses_python_code_block(self, mock_get_model):
        code = "result = cq.Workplane('XY').box(10, 20, 30)"
        _setup_mock_model(mock_get_model, f"```python\n{code}\n```")

        from backend.graph.chains import build_fix_chain

        chain = build_fix_chain()
        result = chain.invoke({"code": "old_code", "fix_instructions": "fix it"})
        assert result == code

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_returns_none_for_no_code_block(self, mock_get_model):
        _setup_mock_model(mock_get_model, "I don't know how to fix this.")

        from backend.graph.chains import build_fix_chain

        chain = build_fix_chain()
        result = chain.invoke({"code": "old_code", "fix_instructions": "fix it"})
        assert result is None

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_with_retry_is_configured(self, mock_get_model):
        fake_llm = _setup_mock_model(mock_get_model, "```python\nx=1\n```")

        from backend.graph.chains import build_fix_chain

        build_fix_chain()
        assert fake_llm.retry_kwargs == {
            "stop_after_attempt": 3,
            "wait_exponential_jitter": True,
        }


# ===================================================================
# Compare Chain
# ===================================================================
class TestCompareChain:
    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_pass_uppercase(self, mock_get_model):
        _setup_mock_model(mock_get_model, "PASS")

        from backend.graph.chains import build_compare_chain

        chain = build_compare_chain(structured=False)
        result = chain.invoke(_COMPARE_INPUT)
        assert result is None

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_pass_lowercase(self, mock_get_model):
        _setup_mock_model(mock_get_model, "pass")

        from backend.graph.chains import build_compare_chain

        chain = build_compare_chain(structured=False)
        result = chain.invoke(_COMPARE_INPUT)
        assert result is None

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_fail_returns_comparison_text(self, mock_get_model):
        feedback = "问题1: 直径偏大\n预期: 50mm\n修改: 减小直径到 50mm"
        _setup_mock_model(mock_get_model, feedback)

        from backend.graph.chains import build_compare_chain

        chain = build_compare_chain(structured=False)
        result = chain.invoke(_COMPARE_INPUT)
        assert result is not None
        assert "直径偏大" in result

    @patch("backend.graph.chains.compare_chain.parse_vl_feedback")
    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_structured_pass_uses_feedback_passed_field(
        self, mock_get_model, mock_parse_vl
    ):
        _setup_mock_model(mock_get_model, '{"verdict":"PASS","issues":[]}')
        mock_feedback = MagicMock()
        mock_feedback.passed = True
        mock_parse_vl.return_value = mock_feedback

        from backend.graph.chains import build_compare_chain

        chain = build_compare_chain(structured=True)
        result = chain.invoke(_COMPARE_INPUT)
        assert result is None
        mock_parse_vl.assert_called_once()

    @patch("backend.graph.chains.compare_chain.parse_vl_feedback")
    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_structured_fail_returns_text(self, mock_get_model, mock_parse_vl):
        raw = '{"verdict":"FAIL","issues":[{"description":"孔数不对"}]}'
        _setup_mock_model(mock_get_model, raw)
        mock_feedback = MagicMock()
        mock_feedback.passed = False
        mock_parse_vl.return_value = mock_feedback

        from backend.graph.chains import build_compare_chain

        chain = build_compare_chain(structured=True)
        result = chain.invoke(_COMPARE_INPUT)
        assert result is not None
        assert "FAIL" in result

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_with_retry_is_configured(self, mock_get_model):
        fake_llm = _setup_mock_model(mock_get_model, "PASS")

        from backend.graph.chains import build_compare_chain

        build_compare_chain(structured=False)
        assert fake_llm.retry_kwargs == {
            "stop_after_attempt": 3,
            "wait_exponential_jitter": True,
        }


# ===================================================================
# Code Gen Chain
# ===================================================================
class TestCodeGenChain:
    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_parses_python_code_block(self, mock_get_model):
        code = "import cadquery as cq\nresult = cq.Workplane('XY').box(10, 20, 30)"
        _setup_mock_model(mock_get_model, f"```python\n{code}\n```")

        from backend.graph.chains import build_code_gen_chain

        chain = build_code_gen_chain()
        result = chain.invoke({"modeling_context": "Build a box 10x20x30"})
        assert "cq.Workplane" in result
        assert "box(10, 20, 30)" in result

    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_returns_none_for_no_code(self, mock_get_model):
        _setup_mock_model(mock_get_model, "I cannot generate code for this spec.")

        from backend.graph.chains import build_code_gen_chain

        chain = build_code_gen_chain()
        result = chain.invoke({"modeling_context": "invalid spec"})
        assert result is None

    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_prompt_contains_modeling_context_variable(self, mock_get_model):
        _setup_mock_model(mock_get_model, "```python\nx=1\n```")

        from backend.graph.chains import build_code_gen_chain

        chain = build_code_gen_chain()
        # Extract prompt runnable (first in chain) and check formatting
        prompt_runnable = chain.first
        prompt_value = prompt_runnable.invoke(
            {"modeling_context": "TEST_MARKER_CONTEXT"}
        )
        prompt_text = str(prompt_value)
        assert "TEST_MARKER_CONTEXT" in prompt_text


# ===================================================================
# Vision Chain
# ===================================================================
class TestVisionChain:
    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_parses_drawing_spec_json(self, mock_get_model):
        spec_json = (
            '```json\n'
            '{"part_type": "rotational", "description": "test cylinder", '
            '"overall_dimensions": {"max_diameter": 50, "total_height": 30}, '
            '"base_body": {"method": "revolve", "profile": [{"diameter": 50, "height": 30}]}, '
            '"features": [], "notes": []}\n'
            '```'
        )
        _setup_mock_model(mock_get_model, spec_json)

        from backend.graph.chains import build_vision_analysis_chain

        chain = build_vision_analysis_chain()
        result = chain.invoke({"image_type": "png", "image_data": "base64data"})
        assert result is not None
        assert hasattr(result, "part_type")
        assert result.part_type.value == "rotational"

    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_returns_none_for_invalid_json(self, mock_get_model):
        _setup_mock_model(mock_get_model, "I cannot analyze this image.")

        from backend.graph.chains import build_vision_analysis_chain

        chain = build_vision_analysis_chain()
        result = chain.invoke({"image_type": "png", "image_data": "base64data"})
        assert result is None

    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_with_retry_is_configured(self, mock_get_model):
        fake_llm = _setup_mock_model(mock_get_model, "no json")

        from backend.graph.chains import build_vision_analysis_chain

        build_vision_analysis_chain()
        assert fake_llm.retry_kwargs == {
            "stop_after_attempt": 3,
            "wait_exponential_jitter": True,
        }


# ===================================================================
# Prompt Equivalence (snapshot tests)
# ===================================================================
class TestPromptEquivalence:
    """Verify LCEL chains produce identical prompts to old SequentialChains."""

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_prompt_text_matches(self, mock_get_model):
        """Same input → same formatted prompt between LCEL and old SmartFixChain."""
        _setup_mock_model(mock_get_model, "```python\nx=1\n```")

        from backend.graph.chains.fix_chain import build_fix_chain
        from backend.core.smart_refiner import _FIX_CODE_PROMPT

        chain = build_fix_chain()
        # Extract the prompt runnable (first in the pipeline)
        prompt_runnable = chain.first
        prompt_value = prompt_runnable.invoke(
            {"code": "test_code", "fix_instructions": "fix this"}
        )
        actual_text = prompt_value.messages[0].content[0]["text"]

        expected_text = _FIX_CODE_PROMPT.format(
            code="test_code", fix_instructions="fix this"
        )
        assert actual_text == expected_text

    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_code_gen_chain_prompt_text_matches(self, mock_get_model):
        _setup_mock_model(mock_get_model, "```python\nx=1\n```")

        from backend.graph.chains.code_gen_chain import build_code_gen_chain
        from backend.core.code_generator import _CODE_GEN_PROMPT

        chain = build_code_gen_chain()
        prompt_runnable = chain.first
        prompt_value = prompt_runnable.invoke(
            {"modeling_context": "Build a cylinder"}
        )
        actual_text = prompt_value.messages[0].content[0]["text"]

        expected_text = _CODE_GEN_PROMPT.format(modeling_context="Build a cylinder")
        assert actual_text == expected_text
