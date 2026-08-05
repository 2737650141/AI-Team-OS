"""任务运行器（M2）：真实 Runtime 的创建 / 澄清暂停 / 恢复 / 状态查询 / 追踪。

- 状态持久化：正式 SQLite Checkpointer（thread_id = run_id）。
- 多智能体：M2 确定性多智能体图（app/graph.py），CLI 与 API 共用本 Runtime。
- 预算/工具网关：恢复时以 checkpoint 中的 budget_usage / idempotency_keys 重建（不清零、不重放）。
- 暂停/恢复场景：澄清 interrupt（vague_goal → resume --clarification）。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.core.budget import BudgetController, BudgetExceeded
from app.core.registry import default_registry
from app.core.resume import ResumePayload
from app.core.schemas import ClarificationPayload
from app.core.state import TaskState
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.gateway.tool_gateway import ToolGateway
from app.graph import build_graph
from app.tools.fixture_repo import (
    DangerousWriteTool,
    FixtureRepositoryLookupTool,
    FixtureSourceLookupTool,
)

DEFAULT_REPO_FIXTURE = Path(__file__).parent / "tools" / "fixtures" / "repos.json"
DEFAULT_SOURCE_FIXTURE = Path(__file__).parent / "tools" / "fixtures" / "sources.json"


@dataclass
class RunReport:
    task_id: str
    run_id: str | None
    state: TaskState
    usage: dict[str, float]
    call_count: int
    tool_call_count: int
    status: str


def _open_conn(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(data_dir / "checkpoints.db"), check_same_thread=False)


def _build_context(
    state: TaskState,
    data_dir: Path,
    model_responses: dict[str, str] | None = None,
):
    """按 checkpoint 状态重建运行时上下文（预算/工具网关带历史，保证不清零、不重放）。"""
    budget = BudgetController(
        state.token_budget,
        state.cost_budget,
        initial_usage=state.budget_usage,
    )
    audit = AuditLog(data_dir / "audit.jsonl")
    fake = DeterministicFakeModel(responses=model_responses)
    model_gateway = ModelGateway(provider=fake, budget=budget, audit=audit, task_id=state.task_id)
    tool_gateway = ToolGateway(
        audit=audit,
        task_id=state.task_id,
        initial_keys=set(state.idempotency_keys),
        initial_calls=[r.model_dump() for r in state.tool_calls],
        initial_evidence=[e.model_dump() for e in state.evidence],
        initial_approvals=[a.model_dump() for a in state.approvals],
    )
    tool_gateway.register(FixtureRepositoryLookupTool(DEFAULT_REPO_FIXTURE).spec())
    tool_gateway.register(FixtureSourceLookupTool(DEFAULT_SOURCE_FIXTURE).spec())
    tool_gateway.register(DangerousWriteTool().spec())
    return budget, audit, fake, model_gateway, tool_gateway


def _compile(
    state: TaskState,
    conn: sqlite3.Connection,
    model_gateway: ModelGateway,
    tool_gateway: ToolGateway,
):
    graph = build_graph(
        model_gateway,
        tool_gateway,
        goal=state.user_goal,
        registry=default_registry(),
    )
    return graph.compile(checkpointer=SqliteSaver(conn))


def run_task(
    goal: str,
    token_budget: int,
    cost_budget: float,
    project_id: str = "default",
    data_dir: Path | None = None,
    model_responses: dict[str, str] | None = None,
) -> RunReport:
    """创建并运行任务（进程 A）。vague_goal 场景在澄清 interrupt 处暂停返回。"""
    data_dir = data_dir or Path("data")
    task_id = uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex[:16]
    state = TaskState(
        task_id=task_id,
        run_id=run_id,
        project_id=project_id,
        user_goal=goal,
        token_budget=token_budget,
        cost_budget=cost_budget,
    )
    budget, audit, fake, model_gateway, tool_gateway = _build_context(
        state, data_dir, model_responses=model_responses
    )
    conn = _open_conn(data_dir)
    try:
        compiled = _compile(state, conn, model_gateway, tool_gateway)
        result = compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": run_id}})
        state = TaskState.model_validate(result)
        if "__interrupt__" in result:
            # 澄清 interrupt：写回 paused（跨进程 status 可读），等待 resume --clarification
            compiled.update_state(
                {"configurable": {"thread_id": run_id}},
                {"current_status": "paused", "paused_from_status": state.current_status},
            )
            state.current_status = "paused"
            state.paused_from_status = state.paused_from_status or "created"
            return RunReport(
                task_id,
                run_id,
                state,
                budget.usage,
                fake.call_count,
                len(tool_gateway.tool_calls),
                "paused",
            )
        # 图已设置最终状态（completed / failed），runner 不覆盖
    except BudgetExceeded as exc:
        # 失败状态写回 checkpoint（与暂停路径的 update_state 一致），跨进程 status 可读
        state.current_status = "failed"
        state.failure_code = "budget_exceeded"
        state.final_result = str(exc)
        compiled.update_state(
            {"configurable": {"thread_id": run_id}},
            {
                "current_status": "failed",
                "failure_code": "budget_exceeded",
                "final_result": str(exc),
                "budget_usage": budget.usage,
            },
        )
    finally:
        conn.close()
    return RunReport(
        task_id,
        run_id,
        state,
        budget.usage,
        fake.call_count,
        len(tool_gateway.tool_calls),
        state.current_status,
    )


def resume_task(
    run_id: str,
    payload: ResumePayload | ClarificationPayload | None = None,
    data_dir: Path | None = None,
) -> RunReport:
    """从 SQLite checkpoint 恢复（进程 B）。

    - 澄清挂起中：必须提供 ClarificationPayload（004 十三，空答案由 Schema 拒绝）。
    - 其余场景：ResumePayload（禁止 None，003-A 三/ADR-0001）。
    """
    if payload is None:
        payload = ResumePayload(action="continue")
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        # 恢复前 Schema 校验：未知枚举值 / schema 版本在 TaskState 边界拒绝
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        # 前置校验：仅 paused 状态可恢复
        if state.current_status != "paused":
            raise RuntimeError(
                f"run {run_id} is not paused "
                f"(current_status={state.current_status!r}); resume rejected"
            )
        # 澄清挂起时恢复值必须为 ClarificationPayload 且 clarification_id 匹配
        if state.pending_clarification_id:
            if not isinstance(payload, ClarificationPayload):
                raise RuntimeError(
                    "run is awaiting clarification; "
                    "provide ClarificationPayload (CLI: --clarification)"
                )
            if payload.clarification_id != state.pending_clarification_id:
                raise RuntimeError(
                    "clarification_id mismatch: "
                    f"{payload.clarification_id} != {state.pending_clarification_id}"
                )
        elif isinstance(payload, ClarificationPayload):
            raise RuntimeError("run is not awaiting clarification")
        budget, audit, fake, model_gateway, tool_gateway = _build_context(state, data_dir)
        compiled = _compile(state, conn, model_gateway, tool_gateway)
        try:
            result = compiled.invoke(
                Command(resume=payload), config={"configurable": {"thread_id": run_id}}
            )
        except BudgetExceeded as exc:
            # 与 run_task 对称：恢复中预算不足时写回 failed
            compiled.update_state(
                {"configurable": {"thread_id": run_id}},
                {
                    "current_status": "failed",
                    "failure_code": "budget_exceeded",
                    "final_result": str(exc),
                    "budget_usage": budget.usage,
                },
            )
            state.current_status = "failed"
            state.failure_code = "budget_exceeded"
            state.final_result = str(exc)
            return RunReport(
                state.task_id,
                run_id,
                state,
                budget.usage,
                fake.call_count,
                len(tool_gateway.tool_calls),
                "failed",
            )
        state = TaskState.model_validate(result)
        # 图已设置最终状态（completed / failed），runner 不覆盖
        return RunReport(
            state.task_id,
            run_id,
            state,
            budget.usage,
            fake.call_count,
            len(tool_gateway.tool_calls),
            state.current_status,
        )
    finally:
        conn.close()


def status_task(run_id: str, data_dir: Path | None = None) -> RunReport:
    """查询任务状态（进程 C）：从 checkpoint 读取，不执行。"""
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        return RunReport(
            state.task_id,
            run_id,
            state,
            state.budget_usage,
            0,
            len(state.tool_calls),
            state.current_status,
        )
    finally:
        conn.close()


def trace_task(run_id: str, data_dir: Path | None = None) -> dict:
    """运行追踪（CLI/API trace）：完整结构化状态快照。"""
    data_dir = data_dir or Path("data")
    conn = _open_conn(data_dir)
    try:
        saver = SqliteSaver(conn)
        checkpoint = saver.get_tuple(config={"configurable": {"thread_id": run_id}})
        if checkpoint is None:
            raise KeyError(f"run not found: {run_id}")
        state = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
        return {
            "task_id": state.task_id,
            "run_id": run_id,
            "current_status": state.current_status,
            "failure_code": state.failure_code,
            "clarified_goal": state.clarified_goal,
            "clarification_history": [c.model_dump() for c in state.clarification_history],
            "plan": state.plan,
            "selected_agents": state.selected_agents,
            "subtasks": [s.model_dump() for s in state.subtasks],
            "review_history": [r.model_dump() for r in state.review_history],
            "rework_count": state.rework_count,
            "evidence": [e.model_dump() for e in state.evidence],
            "final_evidence": [e.model_dump() for e in state.final_evidence],
            "tool_call_count": len(state.tool_calls),
            "budget_usage": state.budget_usage,
            "final_result": state.final_result,
        }
    finally:
        conn.close()
