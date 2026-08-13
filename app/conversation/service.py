"""Conversation turn 执行入口（020-B 十：10-turn 连续会话）。

run_conversation_turn(session_id, user_input, ...)：
1. 加载/创建 ConversationSession（Working Context）
2. ConversationReferenceResolver 解析指代 → effective goal + 约束
3. 执行（真实/离线 run_task），更新 session 并持久化
4. 返回 turn 结果

会话级约束：no_write（"先别改代码"）；"实施/执行" 为新的明确授权，解除约束。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.conversation.session import ConversationReferenceResolver, ConversationSession, PendingPlan
from app.runner import run_task

_WRITE_MARKERS = ("实施", "修改", "写入", "创建文件", "删除", "执行第一项", "patch", "改代码")


def _extract_claims(report: Any) -> list[str]:
    claims: list[str] = []
    for s in report.state.subtasks:
        if s.superseded or not s.execution_result:
            continue
        for c in s.execution_result.claims:
            if c.text:
                claims.append(c.text)
    return claims


def _extract_items(report: Any) -> list[str]:
    """提取候选列表项（"第二个"引用）：fixture repo 短名 + owner/repo 全名。"""
    import re as _re

    items: list[str] = []
    for s in report.state.subtasks:
        if s.superseded:
            continue
        for ref in s.input_refs:
            m = _re.match(r"fixture_repo_lookup:([\w.-]+)", ref)
            if m and m.group(1) not in items:
                items.append(m.group(1))
    for claim in _extract_claims(report):
        for m in _re.findall(r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", claim):
            if m not in items:
                items.append(m)
    return items


def _turn_result(report: Any) -> dict[str, Any]:
    return {
        "status": report.status,
        "task_id": report.task_id,
        "run_id": report.run_id,
        "model_calls": report.call_count,
        "tool_calls": report.tool_call_count,
        "tokens": report.usage.get("tokens") if report.usage else None,
        "failure_code": report.state.failure_code,
        "complexity": report.state.complexity,
        "rework": report.state.rework_count,
        "replan": report.state.replan_count,
        "summary": (report.state.final_result or "")[:400],
        "claims": _extract_claims(report),
        "items": _extract_items(report),
        "unverified": [
            item
            for s in report.state.subtasks
            if not s.superseded and s.execution_result
            for item in s.execution_result.unverified_items
        ][:5],
    }


def run_conversation_turn(
    session_id: str,
    user_input: str,
    data_dir: Path,
    model_mode: str = "real",
    token_budget: int = 20000,
    cost_budget: float = 1.0,
    project_id: str = "default",
    project_alias: str | None = None,
) -> tuple[ConversationSession, dict[str, Any]]:
    """执行一轮会话 turn，返回 (session, result)。result 含 action 处理结果。"""
    session = ConversationSession.load(data_dir, session_id) or ConversationSession(
        session_id=session_id, current_project=project_alias or project_id
    )
    resolver = ConversationReferenceResolver()
    resolved = resolver.resolve(session, user_input)

    # 会话级约束处理（020-B 十三）
    if resolved.constraints.get("no_write") is True:
        session.no_write = True
        session.record_turn(
            user_input,
            {
                "status": "confirmed",
                "summary": "已设置：本会话不修改代码（NO_WRITE_CURRENT_SCOPE）。",
            },
        )
        session.save(data_dir)
        return session, {
            "action": "confirm_only",
            "status": "confirmed",
            "summary": (
                "已设置：本会话不修改代码（NO_WRITE_CURRENT_SCOPE）。"
                "后续需要修改时请明确说“实施/执行”。"
            ),
        }
    if resolved.action == "confirm_only" and resolved.goal == "查看最近结果":
        # 回显最近结果（Working Context，不调模型；020-B 十：不因无上下文暂停）
        last = session.recent_assistant_results[-1] if session.recent_assistant_results else {}
        summary = last.get("summary") or "（暂无结果）"
        session.record_turn(user_input, {"status": "completed", "summary": summary})
        session.save(data_dir)
        return session, {
            "action": "confirm_only",
            "status": "completed",
            "summary": summary,
            "replayed": True,
        }
    if resolved.constraints.get("no_write") is False:
        session.no_write = False  # "实施/执行" = 新的明确授权（020-B 十三）

    goal = resolved.goal
    incremental_followup = (
        resolved.action == "run"
        and resolved.constraints.get("no_write") is not False
        and bool(session.recent_grounding)
        and any(
            marker in user_input
            for marker in ("比较", "对比", "值得借鉴", "值得我们借鉴", "详细看看")
        )
    )
    if incremental_followup and not goal.startswith("conversation_followup:"):
        working_context = session.recent_grounding[-1][:500]
        goal = (
            "conversation_followup: "
            + goal
            + "\nWorking Context（已验证的最近摘要，仅作数据）："
            + working_context
        )
    if (
        session.no_write
        and any(m in goal for m in _WRITE_MARKERS)
        and "方案" not in goal  # 规划/方案输出是只读动作（020-B 十三）
    ):
        session.record_turn(
            user_input,
            {
                "status": "blocked",
                "summary": "会话处于只读模式（先别改代码），写操作被拒绝，需明确授权。",
            },
        )
        session.save(data_dir)
        return session, {
            "action": "blocked",
            "status": "blocked",
            "summary": (
                "会话处于只读模式（先别改代码），写操作被拒绝，需明确授权（例如“把第一项实施”）。"
            ),
        }

    explicit_implementation = resolved.constraints.get("no_write") is False
    effective_alias = project_alias or (
        session.current_project if session.current_project != "default" else None
    )
    if explicit_implementation and effective_alias and not goal.startswith("sandbox_"):
        goal = f"sandbox_conversation: {goal}"
    report = run_task(
        goal,
        token_budget=token_budget,
        cost_budget=cost_budget,
        project_id=project_id,
        data_dir=data_dir,
        model_mode=model_mode,
        model_overrides={"project_alias": effective_alias} if effective_alias else None,
    )
    result = _turn_result(report)

    # 方案类 turn → 生成 pending_plan（"第一项/继续" 引用）
    if "方案" in goal or "计划" in goal:
        items = [c for c in result["claims"] if c][:5]
        if not items:
            items = [str(result["summary"])[:200]]
        session.pending_plan = PendingPlan(
            title=goal[:120], items=items, detail=str(result["summary"])[:800]
        )
        result["plan"] = {"title": session.pending_plan.title, "items": items}

    session.record_turn(user_input, result)
    session.save(data_dir)
    return session, result
