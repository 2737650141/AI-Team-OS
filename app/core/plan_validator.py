"""Plan 确定性校验（004 六，共 10 项）。"""

from __future__ import annotations

from collections import deque

from app.core.orchestration import PlanningEnvelope, RoleRouter
from app.core.registry import AgentRegistry
from app.core.schemas import Plan

# 集中配置：子任务数量上限（004 六.1，禁止散落硬编码）
MAX_SUBTASKS = 8

# 集中配置：运行时真正可执行的角色（PRODUCT-01：exec_subtask 图节点仅支持
# executor / researcher；Planner 不得把 supervisor/planner/reviewer 分配给子任务，
# 否则 validate 放行、执行时 unsupported role 盲重试至 fail_rework_limit）。
EXECUTABLE_ROLES = ("executor", "researcher")


class PlanValidationError(ValueError):
    """Plan 校验失败。code 用于 failed/planning_invalid 的 failure_code 细分。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def validate_plan(
    plan: Plan,
    registry: AgentRegistry,
    task_token_budget: int,
    envelope: PlanningEnvelope | None = None,
) -> None:
    """10 项确定性校验，任一失败抛 PlanValidationError；不得绕过 Schema 继续执行。"""
    # 1. 子任务数量不超过配置上限
    if len(plan.subtasks) > MAX_SUBTASKS:
        raise PlanValidationError(
            "too_many_subtasks",
            f"subtask count {len(plan.subtasks)} exceeds limit {MAX_SUBTASKS}",
        )
    if envelope is not None and len(plan.subtasks) > envelope.max_subtasks:
        raise PlanValidationError(
            "plan_too_complex",
            f"subtask count {len(plan.subtasks)} exceeds envelope {envelope.max_subtasks}",
        )
    if envelope is not None and len(plan.subtasks) < envelope.min_subtasks:
        raise PlanValidationError(
            "plan_too_shallow",
            f"subtask count {len(plan.subtasks)} below envelope {envelope.min_subtasks}",
        )
    # 2. subtask_id 唯一
    ids = [s.subtask_id for s in plan.subtasks]
    if len(set(ids)) != len(ids):
        raise PlanValidationError("duplicate_subtask_id", f"duplicate subtask ids: {ids}")
    # 3. 所有依赖目标存在
    id_set = set(ids)
    for s in plan.subtasks:
        if envelope is not None:
            capability = s.capability_required or "research"
            if capability not in {item.value for item in envelope.allowed_capabilities}:
                raise PlanValidationError(
                    "capability_not_allowed",
                    f"{s.subtask_id} capability {capability} not allowed for {envelope.task_shape}",
                )
            try:
                expected_role = RoleRouter().route(capability)
            except ValueError as exc:
                raise PlanValidationError(
                    "capability_unknown", f"{s.subtask_id} unknown capability {capability}"
                ) from exc
            if s.assigned_role != expected_role:
                raise PlanValidationError(
                    "capability_role_mismatch",
                    f"{s.subtask_id} capability {capability} routes to {expected_role}, "
                    f"not {s.assigned_role}",
                )
        for dep in s.dependencies:
            if dep not in id_set:
                raise PlanValidationError(
                    "missing_dependency", f"{s.subtask_id} depends on unknown {dep}"
                )
    # 4. 依赖图无环
    _assert_acyclic(plan)
    # 5. 子任务预算总和不超过任务总预算
    total = sum(s.token_budget for s in plan.subtasks)
    if total > task_token_budget:
        raise PlanValidationError(
            "over_budget", f"subtask budgets {total} > task budget {task_token_budget}"
        )
    for s in plan.subtasks:
        # 6. 每个子任务有明确产物
        if not s.expected_output:
            raise PlanValidationError("missing_output", f"{s.subtask_id} has no expected_output")
        # 7. 每个子任务有明确验收条件
        if not s.acceptance_criteria:
            raise PlanValidationError(
                "missing_acceptance", f"{s.subtask_id} has no acceptance_criteria"
            )
        # 8. 角色必须存在于 Registry
        try:
            agent = registry.get(s.assigned_role)
        except KeyError as exc:
            raise PlanValidationError(
                "unknown_role", f"{s.subtask_id} role {s.assigned_role} not in registry"
            ) from exc
        # 8.5 角色必须可由运行时执行（PRODUCT-01：Planner 分配不可执行角色
        # 曾导致 unsupported role 盲重试至 rework_limit_exceeded）
        if s.assigned_role not in EXECUTABLE_ROLES:
            raise PlanValidationError(
                "role_not_executable",
                f"{s.subtask_id} role {s.assigned_role} is not executable by the runtime "
                f"(allowed: {', '.join(EXECUTABLE_ROLES)})",
            )
        # 9. 角色必须启用
        if not agent.enabled:
            raise PlanValidationError(
                "role_disabled", f"{s.subtask_id} role {s.assigned_role} is disabled"
            )
        # 10. 角色所需工具必须在白名单中
        for tool in s.required_tools:
            if tool not in agent.allowed_tools:
                raise PlanValidationError(
                    "tools_not_allowed",
                    f"{s.subtask_id} requires {tool} not in {s.assigned_role} whitelist",
                )


def _assert_acyclic(plan: Plan) -> None:
    """拓扑排序检测环（004 六.4）。"""
    indegree: dict[str, int] = {s.subtask_id: 0 for s in plan.subtasks}
    edges: dict[str, list[str]] = {s.subtask_id: [] for s in plan.subtasks}
    for s in plan.subtasks:
        for dep in s.dependencies:
            edges[dep].append(s.subtask_id)
            indegree[s.subtask_id] += 1
    queue = deque([sid for sid, deg in indegree.items() if deg == 0])
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for nxt in edges[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(indegree):
        raise PlanValidationError("cyclic_dependency", "plan dependency graph has a cycle")
