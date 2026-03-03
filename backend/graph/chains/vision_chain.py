"""LCEL chain for drawing vision analysis (replaces DrawingAnalyzerChain).

Input:  ``{"image_type": str, "image_data": str}``
Output: ``DrawingSpec | None``
"""
from __future__ import annotations

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.prompts.image import ImagePromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from backend.core.drawing_analyzer import _DRAWING_ANALYSIS_PROMPT, _parse_drawing_spec
from backend.infra.llm_config_manager import get_model_for_role


def build_vision_analysis_chain() -> Runnable:
    """Sync factory: build LCEL chain for drawing analysis."""
    prompt = ChatPromptTemplate(
        input_variables=["image_type", "image_data"],
        messages=[
            HumanMessagePromptTemplate(
                prompt=[
                    PromptTemplate(
                        input_variables=[],
                        template=_DRAWING_ANALYSIS_PROMPT,
                    ),
                    ImagePromptTemplate(
                        input_variables=["image_type", "image_data"],
                        template={
                            "url": "data:image/{image_type};base64,{image_data}"
                        },
                    ),
                ]
            )
        ],
    )
    llm = get_model_for_role("drawing_analyzer").create_chat_model()

    def _parse(ai_message):
        text = ai_message.content if hasattr(ai_message, "content") else str(ai_message)
        result = _parse_drawing_spec({"text": text})
        return result.get("result")

    return (
        prompt
        | llm.with_retry(stop_after_attempt=3, wait_exponential_jitter=True)
        | RunnableLambda(_parse)
    )
