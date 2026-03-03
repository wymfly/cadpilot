"""LCEL chain for CadQuery code generation (replaces CodeGeneratorChain).

Input:  ``{"modeling_context": str}``
Output: ``str | None``  (generated code or None if parse failed)
"""
from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.code_generator import _CODE_GEN_PROMPT, _parse_code
from backend.infra.llm_config_manager import get_model_for_role


def build_code_gen_chain() -> Runnable:
    """Sync factory: build LCEL chain for CadQuery code generation."""
    prompt = ChatPromptTemplate(
        input_variables=["modeling_context"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["modeling_context"],
                        template=_CODE_GEN_PROMPT,
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("code_generator").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_code({"text": text})
        return result["result"]

    return (
        prompt
        | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        | RunnableLambda(_parse)
    )
