"""Budget Controller 测试：002-A 冻结规则 + GT-09 硬预算（M1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.budget import BudgetController, BudgetExceeded
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway


def test_budget_frozen() -> None:
    """创建后对 LLM 不可修改（冻结规则 2）：只暴露只读属性，无任何修改接口。"""
    budget = BudgetController(token_budget=1000, cost_budget=0.5)
    assert budget.token_budget == 1000
    assert budget.cost_budget == 0.5


def test_allocation_exceeds_budget_rejected() -> None:
    """Planner 分配总和不得超过任务总预算（冻结规则 3）。"""
    budget = BudgetController(token_budget=1000, cost_budget=1.0)
    with pytest.raises(BudgetExceeded):
        budget.allocate_subtasks({"s1": 600, "s2": 500})
    budget.allocate_subtasks({"s1": 600, "s2": 400})  # 总和 == 1000 允许


def test_hard_budget_stops_calls_before_start(tmp_path: Path) -> None:
    """GT-09（M1）：预算不足时不再发起调用；实际消耗不超过硬预算。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(token_budget=2500, cost_budget=1.0)
    fake = DeterministicFakeModel(tokens_per_call=1000)
    gateway = ModelGateway(provider=fake, budget=budget, audit=audit, task_id="t1")

    calls = 0
    while True:
        try:
            gateway.chat([{"role": "user", "content": f"q{calls}"}], max_tokens=512)
            calls += 1
        except BudgetExceeded:
            break

    assert fake.call_count == 2  # 第 3 次调用在发起前被 precheck 拦截
    assert budget.usage["tokens"] <= 2500  # 硬预算，无容差


def test_cost_budget_enforced(tmp_path: Path) -> None:
    """成本预算同样硬性执行。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(token_budget=100_000, cost_budget=0.01)
    fake = DeterministicFakeModel(tokens_per_call=10, cost_per_call=0.006)
    gateway = ModelGateway(provider=fake, budget=budget, audit=audit, task_id="t1")

    calls = 0
    while True:
        try:
            gateway.chat([{"role": "user", "content": f"q{calls}"}], max_tokens=100)
            calls += 1
        except BudgetExceeded:
            break

    assert fake.call_count == 1  # 第 2 次调用前 cost 预算不足
    assert budget.usage["cost"] <= 0.01
