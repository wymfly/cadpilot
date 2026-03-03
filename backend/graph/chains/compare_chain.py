"""LCEL chain for VL comparison (replaces SmartCompareChain).

Input:  ``{"drawing_spec": str, "code": str,
          "original_image_type": str, "original_image_data": str,
          "rendered_image_type": str, "rendered_image_data": str}``
Output: ``str | None``  (comparison text or None if PASS)
"""
from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.prompts.image import ImagePromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.smart_refiner import (
    _COMPARE_PROMPT,
    _STRUCTURED_COMPARE_PROMPT,
    _extract_comparison,
)
from backend.core.vl_feedback import parse_vl_feedback
from backend.infra.llm_config_manager import get_model_for_role


def build_compare_chain(structured: bool = False) -> Runnable:
    """Sync factory: build LCEL chain for VL comparison.

    Args:
        structured: If True, use structured JSON feedback with
            ``parse_vl_feedback().passed`` for PASS detection.
            If False, use text heuristic ``_extract_comparison()``.
    """
    compare_template = _STRUCTURED_COMPARE_PROMPT if structured else _COMPARE_PROMPT
    prompt = ChatPromptTemplate(
        input_variables=[
            "drawing_spec",
            "code",
            "original_image_type",
            "original_image_data",
            "rendered_image_type",
            "rendered_image_data",
        ],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=["drawing_spec", "code"],
                        template=compare_template,
                    ),
                    ImagePromptTemplate(
                        input_variables=["original_image_type", "original_image_data"],
                        template={
                            "url": "data:image/{original_image_type};base64,{original_image_data}"
                        },
                    ),
                    ImagePromptTemplate(
                        input_variables=["rendered_image_type", "rendered_image_data"],
                        template={
                            "url": "data:image/{rendered_image_type};base64,{rendered_image_data}"
                        },
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("refiner_vl").create_chat_model()

    def _parse(ai_message) -> str | None:
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        if structured:
            feedback = parse_vl_feedback(text)
            if feedback and feedback.passed:
                return None
            return text
        result = _extract_comparison({"text": text})
        return result["result"]

    return (
        prompt
        | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        | RunnableLambda(_parse)
    )
