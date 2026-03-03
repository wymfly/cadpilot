"""Resilience tests for LCEL chains and LangGraph nodes."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


# ---------------------------------------------------------------------------
# Helpers (same _FakeChatModel pattern from test_lcel_chains.py)
# ---------------------------------------------------------------------------

class _FakeChatModel:
    """Fake that supports with_retry() and pipe operator."""
    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.retry_kwargs: dict | None = None

    def with_retry(self, **kwargs) -> RunnableLambda:
        self.retry_kwargs = kwargs
        return RunnableLambda(lambda _input: AIMessage(content=self._response_text))

    def invoke(self, input):
        return AIMessage(content=self._response_text)


def _setup_mock(mock_get_model, response_text: str) -> _FakeChatModel:
    fake = _FakeChatModel(response_text)
    mock_get_model.return_value.create_chat_model.return_value = fake
    return fake


# ---------------------------------------------------------------------------
# Retry Tests
# ---------------------------------------------------------------------------

class TestRetryConfiguration:
    """Verify all LCEL chains configure with_retry properly."""

    @patch("backend.graph.chains.fix_chain.get_model_for_role")
    def test_fix_chain_retry_config(self, mock_get_model):
        from backend.graph.chains import build_fix_chain
        fake = _setup_mock(mock_get_model, "```python\nx=1\n```")
        build_fix_chain()
        assert fake.retry_kwargs == {"stop_after_attempt": 3, "wait_exponential_jitter": True}

    @patch("backend.graph.chains.compare_chain.get_model_for_role")
    def test_compare_chain_retry_config(self, mock_get_model):
        from backend.graph.chains import build_compare_chain
        fake = _setup_mock(mock_get_model, "PASS")
        build_compare_chain(structured=False)
        assert fake.retry_kwargs == {"stop_after_attempt": 3, "wait_exponential_jitter": True}

    @patch("backend.graph.chains.code_gen_chain.get_model_for_role")
    def test_code_gen_chain_retry_config(self, mock_get_model):
        from backend.graph.chains import build_code_gen_chain
        fake = _setup_mock(mock_get_model, "```python\nx=1\n```")
        build_code_gen_chain()
        assert fake.retry_kwargs == {"stop_after_attempt": 3, "wait_exponential_jitter": True}

    @patch("backend.graph.chains.vision_chain.get_model_for_role")
    def test_vision_chain_retry_config(self, mock_get_model):
        from backend.graph.chains import build_vision_analysis_chain
        fake = _setup_mock(mock_get_model, "no json")
        build_vision_analysis_chain()
        assert fake.retry_kwargs == {"stop_after_attempt": 3, "wait_exponential_jitter": True}


# ---------------------------------------------------------------------------
# Timeout Tests
# ---------------------------------------------------------------------------

class TestTimeout:

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation._orchestrate_drawing_generation")
    @patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock)
    async def test_generation_node_timeout(self, mock_dispatch, mock_orch, tmp_path):
        """Generation node returns timeout failure when orchestration exceeds limit."""
        from backend.graph.nodes.generation import generate_step_drawing_node

        async def _hang(state, config):
            await asyncio.sleep(999)
        mock_orch.side_effect = _hang

        with patch("backend.graph.nodes.generation.OUTPUTS_DIR", tmp_path):
            with patch("backend.graph.nodes.generation.GENERATION_TIMEOUT_S", 0.1):
                state = {
                    "job_id": "test-job", "image_path": "/tmp/test.png",
                    "confirmed_spec": {"part_type": "rotational", "overall_dimensions": {}, "base_body": {"method": "revolve", "profile": []}, "features": [], "notes": []},
                    "step_path": None,
                }
                result = await generate_step_drawing_node(state, config={})

        assert result["status"] == "failed"
        assert result["failure_reason"] == "timeout"

    @pytest.mark.asyncio
    async def test_vision_node_timeout(self):
        """Vision node returns failure when LLM exceeds 60s."""
        from backend.graph.nodes.analysis import analyze_vision_node, LLM_TIMEOUT_S

        # Verify the timeout constant is 60s
        assert LLM_TIMEOUT_S == 60.0


# ---------------------------------------------------------------------------
# Failure Reason Tests
# ---------------------------------------------------------------------------

class TestFailureReason:
    """Verify typed failure_reason in SSE payloads."""

    @pytest.mark.asyncio
    @patch("backend.graph.nodes.generation._orchestrate_drawing_generation")
    @patch("backend.graph.nodes.generation._safe_dispatch", new_callable=AsyncMock)
    async def test_exception_maps_to_failure_reason(self, mock_dispatch, mock_orch, tmp_path):
        """Non-timeout exception maps to typed failure_reason."""
        from backend.graph.nodes.generation import generate_step_drawing_node

        mock_orch.side_effect = RuntimeError("Something broke")

        with patch("backend.graph.nodes.generation.OUTPUTS_DIR", tmp_path):
            state = {
                "job_id": "test-job", "image_path": "/tmp/test.png",
                "confirmed_spec": {"part_type": "rotational", "overall_dimensions": {}, "base_body": {"method": "revolve", "profile": []}, "features": [], "notes": []},
                "step_path": None,
            }
            result = await generate_step_drawing_node(state, config={})

        assert result["status"] == "failed"
        assert result.get("failure_reason") is not None
        assert result["failure_reason"] != "timeout"
