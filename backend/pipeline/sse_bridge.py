"""PipelineBridge: V2 管道回调 → SSE 事件队列的桥接层。

将 generate_step_v2 的 on_spec_ready / on_progress 回调映射为
结构化 SSE 事件，通过 queue.Queue 供 SSE endpoint 消费。

使用 stdlib queue.Queue（线程安全），而非 asyncio.Queue，
因为回调在 worker 线程中执行。
"""

from __future__ import annotations

import queue
from typing import Any

_STAGE_TO_EVENT: dict[str, str] = {
    "geometry": "generating",
    "candidate": "generating",
    "refinement_round": "refining",
    "cross_section": "refining",
    "drawing_spec_ready": "drawing_spec_ready",
}


class PipelineBridge:
    """将 V2 管道回调转换为 SSE 事件并放入队列。

    用法::

        bridge = PipelineBridge(job_id="abc-123")
        generate_step_v2(
            ...,
            on_spec_ready=bridge.on_spec_ready,
            on_progress=bridge.on_progress,
        )
        bridge.complete(model_url="/files/abc.step")
        # 或
        bridge.fail("生成失败: ...")

    SSE endpoint 从 ``bridge.queue`` 中消费事件。
    """

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()

    # ------------------------------------------------------------------
    # 管道回调
    # ------------------------------------------------------------------

    def on_spec_ready(self, spec: Any, reasoning: str | None = None) -> None:
        """DrawingSpec 就绪时调用，映射为 ``intent_parsed`` 事件。

        ``spec`` 可以是 Pydantic model 或普通 dict。
        """
        spec_data = spec.model_dump() if hasattr(spec, "model_dump") else spec
        self._put({
            "event": "intent_parsed",
            "job_id": self.job_id,
            "data": {
                "spec": spec_data,
                "reasoning": reasoning,
                "message": "图纸分析完成",
            },
        })

    def on_progress(self, stage: str, data: dict[str, Any]) -> None:
        """管道进度回调，按 stage 映射为 ``generating`` 或 ``refining`` 事件。"""
        event_type = _STAGE_TO_EVENT.get(stage, "generating")
        message = self._stage_message(stage, data)
        self._put({
            "event": event_type,
            "job_id": self.job_id,
            "data": {"stage": stage, "message": message, **data},
        })

    # ------------------------------------------------------------------
    # 终端事件
    # ------------------------------------------------------------------

    def printability_checked(
        self, result: dict[str, Any] | None = None,
    ) -> None:
        """可打印性检查完成，发送 ``printability_checked`` 事件。"""
        self._put({
            "event": "printability_checked",
            "job_id": self.job_id,
            "data": {
                "message": "可打印性检查完成",
                "printability": result,
            },
        })

    def complete(
        self,
        model_url: str | None = None,
        step_path: str | None = None,
        printability: dict[str, Any] | None = None,
    ) -> None:
        """生成成功，发送 ``completed`` 事件。"""
        data: dict[str, Any] = {
            "model_url": model_url,
            "step_path": step_path,
            "message": "生成完成",
        }
        if printability is not None:
            data["printability"] = printability
        self._put({
            "event": "completed",
            "job_id": self.job_id,
            "data": data,
        })

    def fail(self, message: str) -> None:
        """生成失败，发送 ``failed`` 事件。"""
        self._put({
            "event": "failed",
            "job_id": self.job_id,
            "data": {"message": message},
        })

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _put(self, event: dict[str, Any]) -> None:
        self.queue.put_nowait(event)

    @staticmethod
    def _stage_message(stage: str, data: dict[str, Any]) -> str:
        """根据 stage 和 data 生成人类可读的中文消息。"""
        if stage == "geometry":
            if data.get("is_valid"):
                return "几何验证通过"
            return "几何验证未通过，继续优化"
        if stage == "refinement_round":
            round_num = data.get("round", "?")
            total = data.get("total", "?")
            status = data.get("status", "")
            return f"模型优化 {round_num}/{total} — {status}"
        if stage == "candidate":
            index = data.get("index", "?")
            total = data.get("total", "?")
            return f"候选评估 {index}/{total}"
        if stage == "cross_section":
            sections = data.get("sections", "?")
            all_ok = data.get("all_ok", False)
            result = "全部通过" if all_ok else "存在偏差"
            return f"截面分析: {sections} 层, {result}"
        return f"处理中: {stage}"
