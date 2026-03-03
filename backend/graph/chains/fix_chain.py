"""LCEL chain for code fix (replaces SmartFixChain).

Input:  ``{"code": str, "fix_instructions": str}``
Output: ``str | None``  (fixed code or None if parse failed)
"""
from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.smart_refiner import _FIX_CODE_PROMPT, _parse_code
from backend.infra.llm_config_manager import get_model_for_role


def build_fix_chain() -> Runnable:
    """Sync factory: build LCEL chain for code fix."""
    prompt = ChatPromptTemplate(
        input_variables=["code", "fix_instructions"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["code", "fix_instructions"],
                        template=_FIX_CODE_PROMPT,
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("refiner_coder").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_code({"text": text})
        return result["result"]

    return (
        prompt
        | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        | RunnableLambda(_parse)
    )
