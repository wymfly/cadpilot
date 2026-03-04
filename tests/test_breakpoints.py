"""Tests for pipeline breakpoint/debug functionality."""

import operator
from typing import Annotated, Any, TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class BPTestState(TypedDict, total=False):
    job_id: str
    node_trace: Annotated[list[dict[str, Any]], operator.add]
    breakpoints: list[str] | None
    data: Annotated[dict[str, Any], lambda a, b: {**a, **b}]
    pipeline_config: dict[str, dict[str, Any]]
    status: str


def _last_completed_node(node_trace: list[dict[str, Any]]) -> str | None:
    """Mirror of builder._last_completed_node for test nodes."""
    for entry in reversed(node_trace):
        if not entry.get("skipped"):
            return entry["node"]
    return None


def _make_node(name: str):
    """Create a test node with breakpoint check (mirrors wrapper algorithm)."""

    async def node_fn(state: dict[str, Any]) -> dict[str, Any]:
        # Disabled check
        node_cfg = (state.get("pipeline_config") or {}).get(name, {})
        if not node_cfg.get("enabled", True):
            return {"node_trace": [{"node": name, "skipped": True, "elapsed_ms": 0}]}

        # Pre-execution breakpoint
        bp_list = state.get("breakpoints") or []
        breakpoint_update: dict[str, Any] = {}
        if bp_list:
            node_trace = state.get("node_trace") or []
            last = _last_completed_node(node_trace)
            if last and (last in bp_list or "__all__" in bp_list):
                resume_val = interrupt({"paused_after": last, "next_node": name})
                if isinstance(resume_val, dict) and "action" in resume_val:
                    action = resume_val["action"]
                    if action == "step":
                        breakpoint_update["breakpoints"] = ["__all__"]
                    elif action == "run":
                        breakpoint_update["breakpoints"] = []

        # Execute
        diff: dict[str, Any] = {
            "data": {name: "done"},
            "node_trace": [{"node": name, "elapsed_ms": 1}],
        }
        if breakpoint_update:
            diff.update(breakpoint_update)
        return diff

    node_fn.__name__ = f"node_{name}"
    return node_fn


def _make_guard():
    """Create a breakpoint guard node (mirrors builder._make_bp_guard)."""

    async def bp_guard(state: dict[str, Any]) -> dict[str, Any]:
        bp_list = state.get("breakpoints") or []
        if not bp_list:
            return {}
        node_trace = state.get("node_trace") or []
        last = _last_completed_node(node_trace)
        if last and (last in bp_list or "__all__" in bp_list):
            resume_val = interrupt({"paused_after": last, "next_node": "__end__"})
            if isinstance(resume_val, dict) and resume_val.get("action") == "run":
                return {"breakpoints": []}
        return {}

    bp_guard.__name__ = "__bp_guard__"
    return bp_guard


def _build_graph(nodes: list[str]):
    """Build a linear graph: a → b → ... → guard → END."""
    workflow = StateGraph(BPTestState)
    for name in nodes:
        workflow.add_node(name, _make_node(name))

    workflow.add_edge(START, nodes[0])
    for i in range(len(nodes) - 1):
        workflow.add_edge(nodes[i], nodes[i + 1])

    # Guard node before END (R3 architecture)
    guard = _make_guard()
    workflow.add_node("__bp_guard__", guard)
    workflow.add_edge(nodes[-1], "__bp_guard__")
    workflow.add_edge("__bp_guard__", END)

    return workflow.compile(checkpointer=MemorySaver())


def _init(tid: str, breakpoints: list[str] | None = None, **extra) -> dict:
    return {
        "job_id": tid, "node_trace": [], "data": {}, "status": "pending",
        **({"breakpoints": breakpoints} if breakpoints else {}),
        **extra,
    }


@pytest.mark.asyncio
class TestBreakpoints:

    async def test_no_breakpoints_runs_to_completion(self):
        """不设断点 → 正常完成。"""
        graph = _build_graph(["a", "b", "c"])
        result = await graph.ainvoke(
            _init("t1"), config={"configurable": {"thread_id": "t1"}},
        )
        assert len(result["node_trace"]) == 3

    async def test_breakpoint_pauses_after_node(self):
        """breakpoints=["a"] → 在 a 后暂停。"""
        graph = _build_graph(["a", "b", "c"])
        cfg = {"configurable": {"thread_id": "t2"}}

        r1 = await graph.ainvoke(_init("t2", breakpoints=["a"]), config=cfg)
        assert len(r1["node_trace"]) == 1
        assert r1["node_trace"][0]["node"] == "a"

        r2 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert len(r2["node_trace"]) == 3

    async def test_all_breakpoint_single_step(self):
        """__all__ → 每个节点后暂停（含 terminal 通过 guard）。"""
        graph = _build_graph(["a", "b", "c"])
        cfg = {"configurable": {"thread_id": "t3"}}

        r1 = await graph.ainvoke(_init("t3", breakpoints=["__all__"]), config=cfg)
        assert len(r1["node_trace"]) == 1  # paused after a

        r2 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert len(r2["node_trace"]) == 2  # paused after b

        r3 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert len(r3["node_trace"]) == 3  # paused after c (guard fires)

        r4 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert len(r4["node_trace"]) == 3  # completes

    async def test_terminal_breakpoint_via_guard(self):
        """R3-G3-1: terminal 断点通过 guard node 触发，无副作用重执行。"""
        exec_count = {"b": 0}

        async def counting_b(state):
            # Same breakpoint logic as _make_node
            bp_list = state.get("breakpoints") or []
            bu = {}
            if bp_list:
                nt = state.get("node_trace") or []
                last = _last_completed_node(nt)
                if last and (last in bp_list or "__all__" in bp_list):
                    rv = interrupt({"paused_after": last, "next_node": "b"})
                    if isinstance(rv, dict) and rv.get("action") == "run":
                        bu["breakpoints"] = []
            exec_count["b"] += 1
            diff = {"data": {"b": "done"}, "node_trace": [{"node": "b", "elapsed_ms": 1}]}
            if bu:
                diff.update(bu)
            return diff

        counting_b.__name__ = "node_b"

        workflow = StateGraph(BPTestState)
        workflow.add_node("a", _make_node("a"))
        workflow.add_node("b", counting_b)
        workflow.add_node("__bp_guard__", _make_guard())
        workflow.add_edge(START, "a")
        workflow.add_edge("a", "b")
        workflow.add_edge("b", "__bp_guard__")
        workflow.add_edge("__bp_guard__", END)

        graph = workflow.compile(checkpointer=MemorySaver())
        cfg = {"configurable": {"thread_id": "t-term"}}

        r1 = await graph.ainvoke(_init("t-term", breakpoints=["b"]), config=cfg)
        assert len(r1["node_trace"]) == 2  # a + b ran
        assert exec_count["b"] == 1  # b executed once

        # Guard paused after b. Resume → completes.
        r2 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert len(r2["node_trace"]) == 2
        assert exec_count["b"] == 1  # b NOT re-executed (guard handled it)

    async def test_disabled_node_no_phantom_retrigger(self):
        """R2-G2-3 + R3-C3-1: disabled 节点不导致幽灵重触发。"""
        graph = _build_graph(["a", "b", "c"])
        cfg = {"configurable": {"thread_id": "t-dis"}}

        r1 = await graph.ainvoke(
            _init("t-dis", breakpoints=["a"], pipeline_config={"b": {"enabled": False}}),
            config=cfg,
        )
        # R4-P2-C fix: trace has 2 entries at pause point, not 1.
        # Flow: a executes → trace=[a]. b disabled → skip trace committed → trace=[a, b(skipped)].
        # c starts → bp check: last_completed("a") in ["a"] → interrupt. c's output NOT committed.
        assert len(r1["node_trace"]) == 2
        assert r1["node_trace"][0]["node"] == "a"
        assert r1["node_trace"][1].get("skipped") is True

        # Resume → c runs (last_completed still "a", but interrupt already consumed)
        r2 = await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        trace = r2["node_trace"]
        assert len(trace) == 3  # a + b(skipped) + c
        assert trace[1].get("skipped") is True

    async def test_resume_step_changes_to_all(self):
        """action=step → breakpoints 变为 __all__。"""
        graph = _build_graph(["a", "b", "c"])
        cfg = {"configurable": {"thread_id": "t-step"}}

        r1 = await graph.ainvoke(_init("t-step", breakpoints=["a"]), config=cfg)
        assert len(r1["node_trace"]) == 1

        r2 = await graph.ainvoke(Command(resume={"action": "step"}), config=cfg)
        assert len(r2["node_trace"]) == 2  # b runs, pauses before c

    async def test_resume_run_clears_breakpoints(self):
        """action=run → 清除 breakpoints，运行到结束。"""
        graph = _build_graph(["a", "b", "c"])
        cfg = {"configurable": {"thread_id": "t-run"}}

        r1 = await graph.ainvoke(_init("t-run", breakpoints=["__all__"]), config=cfg)
        assert len(r1["node_trace"]) == 1

        r2 = await graph.ainvoke(Command(resume={"action": "run"}), config=cfg)
        assert len(r2["node_trace"]) == 3  # all complete

    async def test_no_side_effect_on_resume(self):
        """断点在 pre-execution 位置 → 前一个节点不会重执行。"""
        exec_count = {"a": 0, "b": 0}

        async def counting_a(state):
            exec_count["a"] += 1
            return {"data": {"a": "done"}, "node_trace": [{"node": "a", "elapsed_ms": 1}]}

        async def counting_b(state):
            bp_list = state.get("breakpoints") or []
            bu = {}
            if bp_list:
                nt = state.get("node_trace") or []
                last = _last_completed_node(nt)
                if last and (last in bp_list or "__all__" in bp_list):
                    rv = interrupt({"paused_after": last, "next_node": "b"})
                    if isinstance(rv, dict) and rv.get("action") == "run":
                        bu["breakpoints"] = []
            exec_count["b"] += 1
            diff = {"data": {"b": "done"}, "node_trace": [{"node": "b", "elapsed_ms": 1}]}
            if bu:
                diff.update(bu)
            return diff

        counting_a.__name__ = "node_a"
        counting_b.__name__ = "node_b"

        workflow = StateGraph(BPTestState)
        workflow.add_node("a", counting_a)
        workflow.add_node("b", counting_b)
        workflow.add_node("__bp_guard__", _make_guard())
        workflow.add_edge(START, "a")
        workflow.add_edge("a", "b")
        workflow.add_edge("b", "__bp_guard__")
        workflow.add_edge("__bp_guard__", END)

        graph = workflow.compile(checkpointer=MemorySaver())
        cfg = {"configurable": {"thread_id": "t-side"}}

        await graph.ainvoke(_init("t-side", breakpoints=["a"]), config=cfg)
        assert exec_count["a"] == 1
        assert exec_count["b"] == 0

        await graph.ainvoke(Command(resume={"action": "continue"}), config=cfg)
        assert exec_count["a"] == 1  # NOT re-executed
        assert exec_count["b"] == 1
