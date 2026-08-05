"""Budget Controller：预算冻结 + 记账（Model Gateway 唯一权威入口，002-A 第二节）。"""

from __future__ import annotations


class BudgetExceeded(Exception):
    """预算不足/超限。触发后调用方必须停止发起新的调用（GT-09）。"""

    def __init__(self, kind: str, used: float, limit: float) -> None:
        self.kind = kind
        self.used = used
        self.limit = limit
        super().__init__(f"{kind} budget exceeded: used={used}, limit={limit}")


class BudgetController:
    """任务预算。创建后冻结，对 LLM 不可修改。

    冻结规则（002-A 第二节）：
    1. 任务总预算由 API/用户创建任务时写入。
    2. 创建后对 LLM 不可修改（本类只暴露只读属性）。
    3. Planner 只能产生 subtask_budget_allocations，总和不得超过任务总预算。
    4. 增加任务总预算必须经过用户审批（由 API 层执行，本类不提供修改接口）。
    """

    def __init__(self, token_budget: int, cost_budget: float) -> None:
        self._token_budget = token_budget
        self._cost_budget = cost_budget
        self._used_tokens = 0
        self._used_cost = 0.0

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def cost_budget(self) -> float:
        return self._cost_budget

    @property
    def usage(self) -> dict[str, float]:
        return {"tokens": float(self._used_tokens), "cost": round(self._used_cost, 6)}

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
            self._used_tokens + estimated_input_tokens + estimated_output_tokens
            <= self._token_budget
            and self._used_cost + estimated_cost <= self._cost_budget
        )

    def record(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        """Model Gateway 唯一权威记账入口：超限则拒绝累加并抛异常（实际消耗不超过硬预算）。"""
        add_tokens = input_tokens + output_tokens
        if (
            self._used_tokens + add_tokens > self._token_budget
            or self._used_cost + cost > self._cost_budget
        ):
            raise BudgetExceeded(
                "usage", float(self._used_tokens), float(self._token_budget)
            )
        self._used_tokens += add_tokens
        self._used_cost += cost
