"""Budget Controller：预算冻结 + 记账（Model Gateway 唯一权威入口，002-A 第二节）。"""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(Exception):
    """预算不足/超限。触发后调用方必须停止发起新的调用（GT-09）。"""

    def __init__(self, kind: str, used: float, limit: float) -> None:
        self.kind = kind
        self.used = used
        self.limit = limit
        super().__init__(f"{kind} budget exceeded: used={used}, limit={limit}")


@dataclass(frozen=True)
class BudgetSnapshot:
    """预算只读视图（006 四.1）：冻结快照，不暴露可变控制器，赋值即抛 FrozenInstanceError。"""

    tokens_used: float
    cost_used: float
    token_budget: float
    cost_budget: float
    calls_used: int = 0
    max_calls: int = 30

    @property
    def usage(self) -> dict[str, float]:
        return {
            "tokens": float(self.tokens_used),
            "cost": float(self.cost_used),
            "calls": float(self.calls_used),
        }


class BudgetController:
    """任务预算。创建后冻结，对 LLM 不可修改。

    冻结规则（002-A 第二节）：
    1. 任务总预算由 API/用户创建任务时写入。
    2. 创建后对 LLM 不可修改（本类只暴露只读属性）。
    3. Planner 只能产生 subtask_budget_allocations，总和不得超过任务总预算。
    4. 增加任务总预算必须经过用户审批（由 API 层执行，本类不提供修改接口）。
    """

    def __init__(
        self,
        token_budget: int,
        cost_budget: float,
        initial_usage: dict[str, float] | None = None,
        max_calls: int = 30,
    ) -> None:
        self._token_budget = token_budget
        self._cost_budget = cost_budget
        usage = initial_usage or {}
        self._used_tokens = int(usage.get("tokens", 0.0))
        self._used_cost = float(usage.get("cost", 0.0))
        self._used_calls = int(usage.get("calls", 0.0))
        self._max_calls = max_calls

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def cost_budget(self) -> float:
        return self._cost_budget

    @property
    def usage(self) -> dict[str, float]:
        return {
            "tokens": float(self._used_tokens),
            "cost": round(self._used_cost, 6),
            "calls": float(self._used_calls),
        }

    def allocate_subtasks(self, allocations: dict[str, int]) -> None:
        """Planner 预算分配：总和不得超过任务总预算（冻结规则 3）。"""
        total = sum(allocations.values())
        if total > self._token_budget:
            raise BudgetExceeded("subtask_allocation", float(total), float(self._token_budget))

    def can_call(
        self,
        estimated_input_tokens: int = 0,
        estimated_output_tokens: int = 0,
        estimated_cost: float = 0.0,
    ) -> bool:
        """调用前预算预留：预算不足时不再发起调用（GT-09）。"""
        return (
            self._used_calls < self._max_calls
            and
            self._used_tokens + estimated_input_tokens + estimated_output_tokens
            <= self._token_budget
            and self._used_cost + estimated_cost <= self._cost_budget
        )

    def record(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        """Model Gateway 唯一权威记账入口：超限则拒绝累加并抛异常（实际消耗不超过硬预算）。"""
        add_tokens = input_tokens + output_tokens
        tokens_over = self._used_tokens + add_tokens > self._token_budget
        cost_over = self._used_cost + cost > self._cost_budget
        if tokens_over or cost_over:
            used = (
                float(self._used_tokens + add_tokens)
                if tokens_over
                else float(self._used_cost + cost)
            )
            limit = (
                float(self._cost_budget)
                if cost_over and not tokens_over
                else float(self._token_budget)
            )
            raise BudgetExceeded("usage", used, limit)
        self._used_tokens += add_tokens
        self._used_cost += cost
        self._used_calls += 1
