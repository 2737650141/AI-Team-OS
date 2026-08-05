"""Plan Schema 确定性校验测试（004 六，测试要求 4-7）。"""

from __future__ import annotations

import pytest

from app.agents.planner import make_plan
from app.core.plan_validator import MAX_SUBTASKS, PlanValidationError, validate_plan
from app.core.registry import default_registry
from app.core.schemas import Plan, SubtaskSpec


def _registry():
    return default_registry()


def test_github_compare_plan_valid() -> None:
    plan = make_plan("github_compare_plan", "对比 LangGraph 与 CrewAI")
    validate_plan(plan, _registry(), task_token_budget=10000)
    assert len(plan.subtasks) == 3
    # s3 依赖 s1/s2（依赖图正确）
    s3 = next(s for s in plan.subtasks if s.subtask_id == "s3")
    assert set(s3.dependencies) == {"s1", "s2"}


def test_plan_schema_roundtrip() -> None:
    """Plan Schema 可序列化/反序列化（Pydantic 边界）。"""
    plan = make_plan("github_compare_plan", "对比")
    data = plan.model_dump()
    restored = Plan.model_validate(data)
    assert restored == plan


def test_cyclic_dependency_rejected() -> None:
    """循环依赖拒绝（测试要求 6）。"""
    plan = make_plan("invalid_cycle_plan", "cycle")
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan, _registry(), task_token_budget=10000)
    assert exc_info.value.code == "cyclic_dependency"


def test_over_budget_rejected() -> None:
    """Plan 超预算拒绝（测试要求 7）。"""
    plan = make_plan("over_budget_plan", "over")
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan, _registry(), task_token_budget=5000)
    assert exc_info.value.code == "over_budget"


def test_unknown_role_rejected() -> None:
    plan = make_plan("unknown_agent_plan", "unknown")
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan, _registry(), task_token_budget=10000)
    assert exc_info.value.code == "unknown_role"


def test_executor_role_enabled_after_m3c() -> None:
    """Executor 已启用（007 十二）：指派 executor 的计划通过验证。"""
    plan = Plan(
        goal="x",
        subtasks=[
            SubtaskSpec(
                subtask_id="e1",
                title="写操作",
                objective="x",
                dependencies=[],
                assigned_role="executor",
                input_refs=[],
                expected_output="r",
                acceptance_criteria=["a"],
                required_tools=["sandbox_apply_patch"],
                token_budget=100,
                tool_call_budget=1,
            )
        ],
    )
    validate_plan(plan, _registry(), task_token_budget=10000)  # 不再抛 role_disabled


def test_tools_not_in_whitelist_rejected() -> None:
    """角色所需工具不在白名单：拒绝（004 六.10）。"""
    plan = Plan(
        goal="x",
        subtasks=[
            SubtaskSpec(
                subtask_id="w1",
                title="越权工具",
                objective="x",
                dependencies=[],
                assigned_role="researcher",
                input_refs=[],
                expected_output="r",
                acceptance_criteria=["a"],
                required_tools=["dangerous_write"],
                token_budget=100,
                tool_call_budget=1,
            )
        ],
    )
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan, _registry(), task_token_budget=10000)
    assert exc_info.value.code == "tools_not_allowed"


def test_subtask_count_limit() -> None:
    """子任务数量不超过上限（004 六.1）。"""
    plan = Plan(
        goal="x",
        subtasks=[
            SubtaskSpec(
                subtask_id=f"s{i}",
                title=f"t{i}",
                objective="x",
                dependencies=[],
                assigned_role="researcher",
                input_refs=[],
                expected_output="r",
                acceptance_criteria=["a"],
                token_budget=1,
                tool_call_budget=0,
            )
            for i in range(MAX_SUBTASKS + 1)
        ],
    )
    with pytest.raises(PlanValidationError) as exc_info:
        validate_plan(plan, _registry(), task_token_budget=10000)
    assert exc_info.value.code == "too_many_subtasks"
