"""ReworkProgressGuard（PRODUCT-01，纠偏令 017）。

禁止盲目重试：如果连续多轮返工后失败特征（failure signature）没有变化，
说明重试同一角色/同一方法不会产生进展，必须停止 blind retry 并触发
Supervisor REPLAN（换方法或重新拆任务），而不是继续打相同的死结。

Signature 组成（确定性，可跨进程复现）：
- subtask_id + assigned_role（目标与方法是否变化）
- execution_result 的稳定哈希（输出是否变化）
- review issues 的 failure_code 集合（失败原因是否变化）
- rework_targets（要求的返工方向是否变化）

用法：Reviewer/调度器在每次 reject 后把当前 signature 追加到
SubtaskState.rework_signatures；guard 检查最近 N 条是否完全相同。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# 连续 N 条相同 signature 视为"无进展"（纠偏令 017：连续两次基本相同即停止）
MAX_IDENTICAL_SIGNATURES = 2


def failure_signature(
    subtask_id: str,
    assigned_role: str,
    execution_result: Any | None = None,
    review_codes: list[str] | None = None,
    rework_targets: list[str] | None = None,
) -> str:
    """计算一次失败的稳定特征串。相同串 = 相同失败 = 重试无意义。

    排除时间戳（ts）：cache 命中重跑时 ts 必然变化，但产物内容相同，
    不应让时间戳破坏"无进展"判定。
    """
    parts = [subtask_id, assigned_role]
    if execution_result is not None:
        payload = (
            execution_result.model_dump(mode="json")
            if hasattr(execution_result, "model_dump")
            else execution_result
        )
        if isinstance(payload, dict):
            payload = {k: v for k, v in payload.items() if k != "ts"}
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        parts.append(digest)
    else:
        parts.append("")
    parts.append(",".join(sorted(review_codes or [])))
    parts.append(",".join(sorted(rework_targets or [])))
    return "|".join(parts)


class ReworkProgressGuard:
    """无进展检测器：给定子任务的历史 signature 序列，判断是否已无进展。"""

    def __init__(self, max_identical: int = MAX_IDENTICAL_SIGNATURES) -> None:
        self._max_identical = max_identical

    def has_no_progress(self, signatures: list[str]) -> bool:
        """最近 max_identical 条 signature 完全相同 → 无进展（停止盲重试）。"""
        if not signatures or len(signatures) < self._max_identical:
            return False
        tail = signatures[-self._max_identical :]
        return len(set(tail)) == 1

    def no_progress_subtask_ids(self, subtasks: list[Any]) -> list[str]:
        """返回所有已判定为无进展的 subtask_id（供 Supervisor replan）。"""
        return [
            s.subtask_id
            for s in subtasks
            if getattr(s, "runtime_status", "") == "rejected"
            and self.has_no_progress(getattr(s, "rework_signatures", []) or [])
        ]
