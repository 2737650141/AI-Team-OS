"""Tool Gateway 执行上下文与配额（006 十一）。

ToolPolicy：网关级策略（只读强制、配额上限）。
ToolExecutionContext：单次调用上下文（角色/子任务/调用预算）。
ToolQuota：运行时配额记账（子任务调用数、Evidence 数、读取字节）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.evidence import EvidenceWriter


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToolExecutionContext:
    """006 十一：调用上下文（由确定性调度器构造，模型不可伪造）。"""

    task_id: str
    subtask_id: str
    role: str
    tool_call_budget: int = 5  # 每子任务最大工具调用次数（十二）
    max_evidence: int = 50  # 每子任务最大 Evidence 数（十二）
    max_read_bytes: int = 2 * 1024 * 1024  # 每子任务最大读取字节（十二）


@dataclass
class ToolPolicy:
    """006 十一：网关策略。"""

    read_only_only: bool = True  # M3-B：只允许只读工具
    max_calls_per_subtask: int = 10
    max_evidence_per_task: int = 200
    max_read_bytes_per_task: int = 5 * 1024 * 1024


class ToolQuota:
    """运行时配额记账（006 十一/十二）。线程安全。"""

    def __init__(self, policy: ToolPolicy) -> None:
        self._policy = policy
        self._subtask_calls: dict[str, int] = {}
        self._lock = threading.Lock()

    def check_and_reserve(self, ctx: ToolExecutionContext | None) -> None:
        """调用前检查并预留（超限抛 ValueError 由网关转为 blocked）。"""
        if ctx is None:
            return
        with self._lock:
            used = self._subtask_calls.get(ctx.subtask_id, 0)
            if used >= min(ctx.tool_call_budget, self._policy.max_calls_per_subtask):
                raise ValueError(f"tool call quota exceeded for subtask {ctx.subtask_id}")
            self._subtask_calls[ctx.subtask_id] = used + 1

    def calls_for(self, subtask_id: str) -> int:
        return self._subtask_calls.get(subtask_id, 0)

    def check_evidence(self, writer: EvidenceWriter | None) -> None:
        if writer is not None and writer.count() >= self._policy.max_evidence_per_task:
            raise ValueError(f"evidence quota exceeded: {self._policy.max_evidence_per_task}")

    def check_read_bytes(self, writer: EvidenceWriter | None, additional: int = 0) -> None:
        if writer is not None:
            total = writer.total_bytes() + additional
            if total > self._policy.max_read_bytes_per_task:
                raise ValueError(f"read bytes quota exceeded: {total}")
