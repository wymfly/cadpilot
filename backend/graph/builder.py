"""Build and compile the CadJob StateGraph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.graph.nodes.analysis import (
    analyze_intent_node,
    analyze_vision_node,
    stub_organic_node,
)
from backend.graph.nodes.generation import (
    generate_step_drawing_node,
    generate_step_text_node,
)
from backend.graph.nodes.lifecycle import (
    confirm_with_user_node,
    create_job_node,
    finalize_node,
)
from backend.graph.nodes.postprocess import (
    check_printability_node,
    convert_preview_node,
)
from backend.graph.routing import route_after_confirm, route_by_input_type
from backend.graph.state import CadJobState


def _build_workflow() -> StateGraph:
    """Construct the StateGraph topology (nodes + edges)."""
    workflow = StateGraph(CadJobState)

    # ── Nodes ──
    workflow.add_node("create_job", create_job_node)
    workflow.add_node("analyze_intent", analyze_intent_node)
    workflow.add_node("analyze_vision", analyze_vision_node)
    workflow.add_node("stub_organic", stub_organic_node)
    workflow.add_node("confirm_with_user", confirm_with_user_node)
    workflow.add_node("generate_step_text", generate_step_text_node)
    workflow.add_node("generate_step_drawing", generate_step_drawing_node)
    workflow.add_node("convert_preview", convert_preview_node)
    workflow.add_node("check_printability", check_printability_node)
    workflow.add_node("finalize", finalize_node)

    # ── Edges ──
    workflow.add_edge(START, "create_job")

    workflow.add_conditional_edges(
        "create_job",
        route_by_input_type,
        {"text": "analyze_intent", "drawing": "analyze_vision", "organic": "stub_organic"},
    )

    workflow.add_edge("analyze_intent", "confirm_with_user")
    workflow.add_edge("analyze_vision", "confirm_with_user")
    workflow.add_edge("stub_organic", "confirm_with_user")

    workflow.add_conditional_edges(
        "confirm_with_user",
        route_after_confirm,
        {"text": "generate_step_text", "drawing": "generate_step_drawing", "finalize": "finalize"},
    )

    workflow.add_edge("generate_step_text", "convert_preview")
    workflow.add_edge("generate_step_drawing", "convert_preview")
    workflow.add_edge("convert_preview", "check_printability")
    workflow.add_edge("check_printability", "finalize")
    workflow.add_edge("finalize", END)

    return workflow


def build_graph():
    """Compile graph without checkpointer (for testing)."""
    return _build_workflow().compile()


async def get_compiled_graph():
    """Compile graph with MemorySaver checkpointer for HITL support.

    Uses in-memory checkpointing which is sufficient for single-worker
    deployments where each job is a one-shot run.

    Note: MemorySaver only supports a single worker process. For
    multi-worker deployments, switch to a persistent checkpointer.
    """
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()

    compiled = _build_workflow().compile(
        checkpointer=checkpointer,
        interrupt_before=["confirm_with_user"],
    )
    return compiled
