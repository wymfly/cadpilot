"""Build and compile the CadJob StateGraph."""

from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

from backend.graph.nodes.analysis import (
    analyze_intent_node,
    analyze_vision_node,
)
from backend.graph.nodes.organic import (
    analyze_organic_node,
    generate_organic_mesh_node,
    postprocess_organic_node,
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
    workflow.add_node("analyze_organic", analyze_organic_node)
    workflow.add_node("confirm_with_user", confirm_with_user_node)
    workflow.add_node("generate_step_text", generate_step_text_node)
    workflow.add_node("generate_step_drawing", generate_step_drawing_node)
    workflow.add_node("generate_organic_mesh", generate_organic_mesh_node)
    workflow.add_node("postprocess_organic", postprocess_organic_node)
    workflow.add_node("convert_preview", convert_preview_node)
    workflow.add_node("check_printability", check_printability_node)
    workflow.add_node("finalize", finalize_node)

    # ── Edges ──
    workflow.add_edge(START, "create_job")

    workflow.add_conditional_edges(
        "create_job",
        route_by_input_type,
        {"text": "analyze_intent", "drawing": "analyze_vision", "organic": "analyze_organic"},
    )

    workflow.add_edge("analyze_intent", "confirm_with_user")
    workflow.add_edge("analyze_vision", "confirm_with_user")
    workflow.add_edge("analyze_organic", "confirm_with_user")

    workflow.add_conditional_edges(
        "confirm_with_user",
        route_after_confirm,
        {
            "text": "generate_step_text",
            "drawing": "generate_step_drawing",
            "generate_organic_mesh": "generate_organic_mesh",
            "finalize": "finalize",
        },
    )

    workflow.add_edge("generate_step_text", "convert_preview")
    workflow.add_edge("generate_step_drawing", "convert_preview")
    workflow.add_edge("generate_organic_mesh", "postprocess_organic")
    workflow.add_edge("postprocess_organic", "finalize")
    workflow.add_edge("convert_preview", "check_printability")
    workflow.add_edge("check_printability", "finalize")
    workflow.add_edge("finalize", END)

    return workflow


def build_graph():
    """Compile graph without checkpointer (for testing)."""
    return _build_workflow().compile()


async def get_compiled_graph():
    """Compile graph with a persistent SQLite checkpointer for HITL support.

    Uses ``AsyncSqliteSaver`` so that graph state survives process restarts.
    Falls back to in-memory ``MemorySaver`` when the SQLite checkpointer is
    unavailable (e.g. missing dependency or filesystem error).
    """
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        db_path = Path("backend/data/checkpoints.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        checkpointer = AsyncSqliteSaver.from_conn_string(str(db_path))
        await checkpointer.setup()
        logger.info("Using persistent SQLite checkpointer at %s", db_path)
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        logger.warning(
            "langgraph-checkpoint-sqlite not installed, using MemorySaver "
            "(state lost on restart)"
        )
    except Exception as exc:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        logger.warning(
            "SQLite checkpointer setup failed (%s), using MemorySaver "
            "(state lost on restart)",
            exc,
        )

    compiled = _build_workflow().compile(
        checkpointer=checkpointer,
        interrupt_before=["confirm_with_user"],
    )
    return compiled
