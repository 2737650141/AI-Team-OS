"""任务运行器（M1）：CLI 与 API 共用。"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.budget import BudgetController, BudgetExceeded
from app.core.state import FailureCode, TaskState, TaskStatus
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.graph import build_graph


@dataclass
class RunReport:
    task_id: str
    state: TaskState
    usage: dict[str, float]
    call_count: int
    status: str


def run_task(
    goal: str,
    token_budget: int,
    cost_budget: float,
    project_id: str = "default",
    data_dir: Path | None = None,
    model_responses: dict[str, str] | None = None,
) -> RunReport:
    """创建并运行一个任务（M1：DeterministicFakeModel）。预算创建后冻结。"""
    data_dir = data_dir or Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex[:12]

    state = TaskState(
        task_id=task_id,
        project_id=project_id,
        user_goal=goal,
        token_budget=token_budget,
        cost_budget=cost_budget,
    )
    budget = BudgetController(token_budget=token_budget, cost_budget=cost_budget)
    audit = AuditLog(data_dir / "audit.jsonl")
    fake = DeterministicFakeModel(responses=model_responses)
    gateway = ModelGateway(provider=fake, budget=budget, audit=audit, task_id=task_id)

    conn = sqlite3.connect(str(data_dir / "checkpoints.db"), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = build_graph(gateway).compile(checkpointer=checkpointer)

    try:
        result = compiled.invoke(
            state.model_dump(), config={"configurable": {"thread_id": task_id}}
        )
        state = TaskState.model_validate(result)
        state.current_status = TaskStatus.COMPLETED
    except BudgetExceeded as exc:
        state.current_status = TaskStatus.FAILED
        state.failure_code = FailureCode.BUDGET_EXCEEDED
        state.final_result = str(exc)

    return RunReport(
        task_id=task_id,
        state=state,
        usage=budget.usage,
        call_count=fake.call_count,
        status=state.current_status.value,
    )
