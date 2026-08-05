"""任务运行器（M1 + 003-A 二）：真实 Runtime 的创建 / 暂停 / 恢复 / 状态查询。

- 状态持久化：正式 SQLite Checkpointer（thread_id = run_id）。
- 预算：恢复时以 checkpoint 中的 budget_usage 重建 BudgetController（不清零）。
- 工具：恢复时以 checkpoint 中的 idempotency_keys / tool_calls / evidence / approvals
  重建 ToolGateway（幂等键继续有效，已成功工具不重复执行）。
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.core.budget import BudgetController, BudgetExceeded
from app.core.resume import ResumePayload
from app.core.state import TaskState
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.gateway.tool_gateway import ToolGateway
from app.graph import build_graph
from app.tools.fixture_repo import DangerousWriteTool, FixtureRepositoryLookupTool

DEFAULT_FIXTURE = Path(__file__).parent / "tools" / "fixtures" / "repos.json"


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
    fixture_path: Path | None = None,
    model_responses: dict[str, str] | None = None,
):
    """按 checkpoint 状态重建运行时上下文（预算/工具网关带历史，保证不清零、不重放）。"""
    fixture_path = fixture_path or DEFAULT_FIXTURE
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
    tool_gateway.register(FixtureRepositoryLookupTool(fixture_path).spec())
    tool_gateway.register(DangerousWriteTool().spec())
    return budget, audit, fake, model_gateway, tool_gateway


def _compile(
    state: TaskState,
    conn: sqlite3.Connection,
    model_gateway: ModelGateway,
    tool_gateway: ToolGateway,
):
    graph = build_graph(model_gateway, tool_gateway, pause_after=state.pause_after)
    return graph.compile(checkpointer=SqliteSaver(conn))


def run_task(
    goal: str,
    token_budget: int,
    cost_budget: float,
    project_id: str = "default",
    data_dir: Path | None = None,
    model_responses: dict[str, str] | None = None,
    pause_after: str | None = None,
) -> RunReport:
    """创建并运行任务（进程 A）。pause_after="agent" 时在节点边界暂停并返回。"""
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
        pause_after=pause_after,
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
            # 节点边界暂停：把 paused 状态写回 checkpoint（HITL update_state），
            # 进程可退出；恢复由 resume_task 处理（current_status 从 checkpoint 读取）
            compiled.update_state(
                {"configurable": {"thread_id": run_id}},
                {"current_status": "paused", "paused_from_status": "executing"},
            )
            state.current_status = "paused"
            state.paused_from_status = "executing"
            return RunReport(
                task_id,
                run_id,
                state,
                budget.usage,
                fake.call_count,
                len(tool_gateway.tool_calls),
                "paused",
            )
        state.current_status = "completed"
    except BudgetExceeded as exc:
        state.current_status = "failed"
        state.failure_code = "budget_exceeded"
        state.final_result = str(exc)
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
    payload: ResumePayload | None = None,
    data_dir: Path | None = None,
) -> RunReport:
    """从 SQLite checkpoint 恢复（进程 B）。payload 禁止为 None（003-A 三）。"""
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
        budget, audit, fake, model_gateway, tool_gateway = _build_context(state, data_dir)
        compiled = _compile(state, conn, model_gateway, tool_gateway)
        result = compiled.invoke(
            Command(resume=payload), config={"configurable": {"thread_id": run_id}}
        )
        state = TaskState.model_validate(result)
        state.current_status = "completed"
        return RunReport(
            state.task_id,
            run_id,
            state,
            budget.usage,
            fake.call_count,
            len(tool_gateway.tool_calls),
            "completed",
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
