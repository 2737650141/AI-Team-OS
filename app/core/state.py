"""统一任务状态模型（STATE_MODEL 最小落地子集，M1）。

003-A 四：Checkpoint 中保存稳定字符串值，Pydantic 边界再转换为 Enum。
TaskStatusStr / FailureCodeStr 为"字符串 + 枚举成员校验"，未知值在恢复时拒绝。
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field

CHECKPOINT_VERSION = "1.0"


class TaskStatus(str, Enum):
    """统一状态枚举（002-A 第四节，12 值）。"""

    CREATED = "created"
    CLARIFYING = "clarifying"
    CLARIFIED = "clarified"
    PLANNING = "planning"
    DISPATCHING = "dispatching"
    EXECUTING = "executing"
    AWAITING_APPROVAL = "awaiting_approval"
    REVIEWING = "reviewing"
    REWORKING = "reworking"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureCode(str, Enum):
    """错误原因独立保存，不作为状态值（002-A 第四节）。"""

    LOOP_DETECTED = "loop_detected"
    BUDGET_EXCEEDED = "budget_exceeded"
    SCHEMA_INVALID = "schema_invalid"
    TOOL_BLOCKED = "tool_blocked"


def _validate_status(value: Any) -> str:
    """稳定字符串 + 枚举成员校验：未知状态值在恢复/反序列化时拒绝。"""
    s = str(value)
    if s not in TaskStatus._value2member_map_:
        raise ValueError(f"unknown task status: {s!r}")
    return s


def _validate_failure_code(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    if s not in FailureCode._value2member_map_:
        raise ValueError(f"unknown failure code: {s!r}")
    return s


TaskStatusStr = Annotated[str, AfterValidator(_validate_status)]
FailureCodeStr = Annotated[str | None, AfterValidator(_validate_failure_code)]


class ToolCallRecord(BaseModel):
    id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    status: str  # ok | blocked | error | skipped
    idempotency_key: str
    ts: str
    role: str | None = None
    result_summary: str | None = None


class Evidence(BaseModel):
    id: str
    task_id: str
    tool: str
    summary: str
    ts: str


class Approval(BaseModel):
    id: str
    task_id: str
    tool: str
    args_summary: str
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None
    ts: str


class TaskState(BaseModel):
    """LangGraph 状态（单一事实源）。"""

    task_id: str
    run_id: str | None = None
    pause_after: str | None = None
    project_id: str = "default"
    user_goal: str
    current_status: TaskStatusStr = "created"
    # 预算：创建时由 API/用户写入，对 LLM 不可修改（002-A 第二节）
    token_budget: int = Field(gt=0)
    cost_budget: float = Field(gt=0)
    budget_usage: dict[str, float] = Field(default_factory=lambda: {"tokens": 0.0, "cost": 0.0})
    subtask_budget_allocations: dict[str, int] = Field(default_factory=dict)
    checkpoint_version: str = CHECKPOINT_VERSION
    failure_code: FailureCodeStr = None
    paused_from_status: TaskStatusStr | None = None
    idempotency_keys: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    final_result: str | None = None
