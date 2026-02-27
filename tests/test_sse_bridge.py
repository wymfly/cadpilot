"""Tests for PipelineBridge — V2 管道回调 → SSE 事件映射。"""

from __future__ import annotations

import queue

from backend.pipeline.sse_bridge import PipelineBridge


class _FakeSpec:
    """模拟 Pydantic model，带 model_dump 方法。"""

    def __init__(self, data: dict) -> None:
        self._data = data

    def model_dump(self) -> dict:
        return self._data


class TestOnSpecReady:
    """on_spec_ready → intent_parsed 事件。"""

    def test_pydantic_model(self) -> None:
        bridge = PipelineBridge(job_id="job-1")
        spec = _FakeSpec({"part_type": "ROTATIONAL", "dims": {"d": 50}})

        bridge.on_spec_ready(spec, reasoning="回转体特征明显")

        event = bridge.queue.get_nowait()
        assert event["event"] == "intent_parsed"
        assert event["job_id"] == "job-1"
        assert event["data"]["spec"] == {"part_type": "ROTATIONAL", "dims": {"d": 50}}
        assert event["data"]["reasoning"] == "回转体特征明显"
        assert event["data"]["message"] == "图纸分析完成"

    def test_dict_spec(self) -> None:
        bridge = PipelineBridge(job_id="job-2")
        spec_dict = {"part_type": "PLATE", "thickness": 10}

        bridge.on_spec_ready(spec_dict)

        event = bridge.queue.get_nowait()
        assert event["event"] == "intent_parsed"
        assert event["data"]["spec"] == {"part_type": "PLATE", "thickness": 10}
        assert event["data"]["reasoning"] is None


class TestOnProgressGenerating:
    """on_progress("geometry"|"candidate") → generating 事件。"""

    def test_geometry_valid(self) -> None:
        bridge = PipelineBridge(job_id="job-3")

        bridge.on_progress("geometry", {"is_valid": True, "volume": 1234.5})

        event = bridge.queue.get_nowait()
        assert event["event"] == "generating"
        assert event["data"]["stage"] == "geometry"
        assert event["data"]["message"] == "几何验证通过"
        assert event["data"]["is_valid"] is True
        assert event["data"]["volume"] == 1234.5

    def test_geometry_invalid(self) -> None:
        bridge = PipelineBridge(job_id="job-4")

        bridge.on_progress("geometry", {"is_valid": False, "error": "no solid"})

        event = bridge.queue.get_nowait()
        assert event["event"] == "generating"
        assert event["data"]["message"] == "几何验证未通过，继续优化"

    def test_candidate(self) -> None:
        bridge = PipelineBridge(job_id="job-5")

        bridge.on_progress("candidate", {"index": 2, "total": 3, "score": 85})

        event = bridge.queue.get_nowait()
        assert event["event"] == "generating"
        assert event["data"]["message"] == "候选评估 2/3"


class TestOnProgressRefining:
    """on_progress("refinement_round"|"cross_section") → refining 事件。"""

    def test_refinement_round(self) -> None:
        bridge = PipelineBridge(job_id="job-6")

        bridge.on_progress("refinement_round", {
            "round": 2,
            "total": 3,
            "status": "refined",
        })

        event = bridge.queue.get_nowait()
        assert event["event"] == "refining"
        assert event["data"]["stage"] == "refinement_round"
        assert event["data"]["message"] == "模型优化 2/3 — refined"

    def test_cross_section(self) -> None:
        bridge = PipelineBridge(job_id="job-7")

        bridge.on_progress("cross_section", {"sections": 5, "all_ok": True})

        event = bridge.queue.get_nowait()
        assert event["event"] == "refining"
        assert event["data"]["message"] == "截面分析: 5 层, 全部通过"


class TestComplete:
    """complete() → completed 事件。"""

    def test_with_model_url(self) -> None:
        bridge = PipelineBridge(job_id="job-8")

        bridge.complete(model_url="/files/abc.step")

        event = bridge.queue.get_nowait()
        assert event["event"] == "completed"
        assert event["job_id"] == "job-8"
        assert event["data"]["model_url"] == "/files/abc.step"
        assert event["data"]["message"] == "生成完成"

    def test_with_step_path(self) -> None:
        bridge = PipelineBridge(job_id="job-9")

        bridge.complete(step_path="/tmp/output.step")

        event = bridge.queue.get_nowait()
        assert event["event"] == "completed"
        assert event["data"]["step_path"] == "/tmp/output.step"


class TestFail:
    """fail() → failed 事件。"""

    def test_fail(self) -> None:
        bridge = PipelineBridge(job_id="job-10")

        bridge.fail("CadQuery 执行超时")

        event = bridge.queue.get_nowait()
        assert event["event"] == "failed"
        assert event["job_id"] == "job-10"
        assert event["data"]["message"] == "CadQuery 执行超时"


class TestQueueOrdering:
    """队列中事件顺序与回调调用顺序一致。"""

    def test_ordering_preserved(self) -> None:
        bridge = PipelineBridge(job_id="job-11")

        # 模拟完整管道流程
        bridge.on_spec_ready({"part_type": "GEAR"})
        bridge.on_progress("geometry", {"is_valid": True})
        bridge.on_progress("refinement_round", {"round": 1, "total": 2, "status": "refined"})
        bridge.on_progress("refinement_round", {"round": 2, "total": 2, "status": "PASS"})
        bridge.complete(model_url="/files/gear.step")

        events = []
        while not bridge.queue.empty():
            events.append(bridge.queue.get_nowait())

        assert len(events) == 5
        assert [e["event"] for e in events] == [
            "intent_parsed",
            "generating",
            "refining",
            "refining",
            "completed",
        ]

    def test_queue_empty_after_drain(self) -> None:
        bridge = PipelineBridge(job_id="job-12")
        bridge.on_spec_ready({"part_type": "PLATE"})

        bridge.queue.get_nowait()

        # 队列应为空
        try:
            bridge.queue.get_nowait()
            assert False, "Expected queue.Empty"
        except queue.Empty:
            pass
