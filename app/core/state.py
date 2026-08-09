"""统一任务状态模型（STATE_MODEL 最小落地子集，M1）。

003-A 四：Checkpoint 中保存稳定字符串值，Pydantic 边界再转换为 Enum。
TaskStatusStr / FailureCodeStr 为"字符串 + 枚举成员校验"，未知值在恢复时拒绝。
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field

from app.core.schemas import (
    ClarificationRecord,
    ExecutionResult,
    ReviewResult,
    SubtaskSpec,
)

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
    PLANNING_INVALID = "planning_invalid"
    REWORK_LIMIT_EXCEEDED = "rework_limit_exceeded"
    INFORMATION_INSUFFICIENT = "information_insufficient"
    FINALIZE_CONDITIONS_NOT_MET = "finalize_conditions_not_met"


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
    subtask_id: str | None = None
    source_type: str | None = None
    source_uri: str | None = None
    title: str = ""
    content_hash: str = ""
    content_length: int = 0
    reliability: float | None = None
    freshness: str | None = None
    snapshot_ref: str | None = None
    truncated: bool = False


class Approval(BaseModel):
    id: str
    task_id: str
    tool: str
    args_summary: str
    status: str = "pending"  # pending | approved | rejected
    decided_by: str | None = None
    ts: str


class SubtaskState(SubtaskSpec):
    """子任务状态：spec 字段由 Planner 创建，运行时字段由确定性节点更新（004 四）。"""

    runtime_status: str = "pending"  # pending | running | passed | rejected
    execution_result: ExecutionResult | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    review_history: list[ReviewResult] = Field(default_factory=list)
    rework_count: int = 0


def merge_subtasks(left: list[SubtaskState], right: list[SubtaskState]) -> list[SubtaskState]:
    """LangGraph 官方 reducer 机制：按 subtask_id 分片合并，并行子任务互不覆盖（004 四/八）。"""
    merged = {s.subtask_id: s for s in left}
    for s in right:
        merged[s.subtask_id] = s
    return list(merged.values())


def _record_id(item: Any) -> Any:
    return item.get("id") if isinstance(item, dict) else item.id


def merge_tool_calls(left: list[Any], right: list[Any]) -> list[Any]:
    """按记录 id 去重合并：并行 exec 回写全量快照时不重复（004 四：共享列表用官方 reducer）。"""
    merged = {_record_id(c): c for c in left}
    for c in right:
        merged[_record_id(c)] = c
    return list(merged.values())


def merge_evidence(left: list[Any], right: list[Any]) -> list[Any]:
    merged = {_record_id(e): e for e in left}
    for e in right:
        merged[_record_id(e)] = e
    return list(merged.values())


def merge_keys(left: list[str], right: list[str]) -> list[str]:
    return list(dict.fromkeys([*left, *right]))


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
    max_model_calls: int = Field(default=30, gt=0, le=100)
    budget_usage: dict[str, float] = Field(
        default_factory=lambda: {"tokens": 0.0, "cost": 0.0, "calls": 0.0}
    )
    subtask_budget_allocations: dict[str, int] = Field(default_factory=dict)
    checkpoint_version: str = CHECKPOINT_VERSION
    failure_code: FailureCodeStr = None
    paused_from_status: TaskStatusStr | None = None
    idempotency_keys: Annotated[list[str], merge_keys] = Field(default_factory=list)
    tool_calls: Annotated[list[ToolCallRecord], merge_tool_calls] = Field(default_factory=list)
    evidence: Annotated[list[Evidence], merge_evidence] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    final_result: str | None = None
    model_mode: str = "fake"  # fake | real（005 十六；真实调用必须服务端显式允许）
    permission_mode: str = "standard"  # standard | full_access; only user/API may set it
    # ===== M2 多智能体字段（004 四） =====
    clarified_goal: str | None = None
    clarification_history: Annotated[list[ClarificationRecord], operator.add] = Field(
        default_factory=list
    )
    plan: dict[str, Any] | None = None
    subtasks: Annotated[list[SubtaskState], merge_subtasks] = Field(default_factory=list)
    selected_agents: dict[str, str] = Field(default_factory=dict)
    review_history: Annotated[list[ReviewResult], operator.add] = Field(default_factory=list)
    rework_count: int = 0
    final_evidence: list[Evidence] = Field(default_factory=list)
    current_subtask_id: str | None = None
    pending_clarification_id: str | None = None
    pending_approval_id: str | None = None  # 007 5.4：审批 interrupt 暂停标记
    # M4-A：Checkpoint 仅保存引用，正文每次角色使用前从 MemoryStore 重新校验。
    memory_refs: list[dict[str, Any]] = Field(default_factory=list)
    # M4-B：派生配置快照用于透明追踪；不包含安全权限或新的事实来源。
    personalization_applied: list[dict[str, Any]] = Field(default_factory=list)
