"""ContextBuilder（005 十四）：角色上下文构建与裁剪。

- 只给角色传必要信息（14.1）。
- 控制最大 Token；超限先裁剪低优先级历史再确定性摘要（14.2）。
- Evidence 以引用形式传入；不传 API Key；不传其他 Agent 隐藏推理；
  不将完整 RuntimeState 全量塞给每个角色。
"""

from __future__ import annotations

from typing import Any

from app.core.config import AppSettings


class ContextBuilder:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._max_chars = 24000  # 约 6k token 的角色上下文上限

    # ---- 角色上下文（14.1） ----
    def supervisor_context(self, state) -> dict[str, Any]:
        return {
            "goal": state.user_goal,
            "clarified_goal": state.clarified_goal,
            "plan_summary": (state.plan or {}).get("goal", ""),
            "subtask_status": [
                {"subtask_id": s.subtask_id, "status": s.runtime_status, "title": s.title}
                for s in state.subtasks
            ],
            "error_summary": state.final_result or "",
        }

    def planner_context(self, state, agents: list[str]) -> dict[str, Any]:
        return {
            "goal": state.clarified_goal or state.user_goal,
            "constraints": {"token_budget": state.token_budget, "cost_budget": state.cost_budget},
            "agents": agents,
        }

    def researcher_context(self, subtask, evidence: list[dict]) -> dict[str, Any]:
        # Evidence 以引用形式传入（截断摘要，不传完整原始内容）
        return {
            "subtask": {
                "subtask_id": subtask.subtask_id,
                "objective": subtask.objective,
                "input_refs": subtask.input_refs,
                "acceptance_criteria": subtask.acceptance_criteria,
                "rework_count": subtask.rework_count,
            },
            "evidence": [
                {"id": e["id"], "tool": e["tool"], "summary": e.get("summary", "")[:300]}
                for e in evidence
            ],
        }

    def reviewer_context(self, state, subtask, deterministic_issues: list[Any]) -> dict[str, Any]:
        return {
            "requirement": subtask.objective,
            "acceptance": subtask.acceptance_criteria,
            "artifact": (
                subtask.execution_result.model_dump()
                if subtask.execution_result
                else {"error": "no artifact"}
            ),
            "evidence": [
                {"id": e["id"], "summary": e.get("summary", "")[:300]} for e in state.evidence
            ],
            "deterministic_issues": [i.model_dump() for i in deterministic_issues],
        }

    # ---- 裁剪（14.2） ----
    def truncate(self, text: str) -> tuple[str, bool]:
        """超限裁剪：保留前缀关键内容并记录 context_truncated=true。"""
        if len(text) <= self._max_chars:
            return text, False
        return text[: self._max_chars], True

    def truncate_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], bool]:
        """裁剪消息历史：优先裁剪中间历史，保留首尾系统/用户约束。"""
        total = sum(len(m.get("content", "")) for m in messages)
        if total <= self._max_chars:
            return messages, False
        kept: list[dict[str, str]] = [messages[0]] if messages else []
        tail: list[dict[str, str]] = []
        budget = (
            self._max_chars - len(messages[0].get("content", "")) if messages else self._max_chars
        )
        for m in reversed(messages[1:]):
            cost = len(m.get("content", ""))
            if budget - cost >= 0:
                tail.insert(0, m)
                budget -= cost
            else:
                break
        kept.extend(tail)
        return kept, True
