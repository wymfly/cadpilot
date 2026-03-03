"""LCEL chain builders — sync factories returning Runnable objects.

Each factory assembles a ``prompt | llm.with_retry() | parser`` pipeline.
Callers invoke via ``await chain.ainvoke(inputs)`` in async nodes.

Usage::

    chain = build_fix_chain()
    result = await chain.ainvoke({"code": ..., "fix_instructions": ...})
"""

from .code_gen_chain import build_code_gen_chain
from .compare_chain import build_compare_chain
from .fix_chain import build_fix_chain
from .vision_chain import build_vision_analysis_chain

__all__ = [
    "build_code_gen_chain",
    "build_compare_chain",
    "build_fix_chain",
    "build_vision_analysis_chain",
]
