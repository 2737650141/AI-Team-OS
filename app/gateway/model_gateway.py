"""Model Gateway：统一 Provider 接口 + DeterministicFakeModel + 唯一预算记账。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.budget import BudgetController, BudgetExceeded
from app.gateway.audit import AuditLog


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    cost: float


class LLMProvider(Protocol):
    """真实 Provider 的接口定义（002-A：M1 只保留接口，不作为验收条件）。"""

    def chat(self, messages: list[dict[str, str]], model: str, max_tokens: int) -> LLMResponse:
        """同步 chat 调用；usage 必须如实返回。"""

    def estimate_cost(self, max_tokens: int) -> float:
        """调用前成本估算（用于预算预留）；无法估算时返回 0.0。"""


class DeterministicFakeModel:
    """确定性假模型：按预设映射返回，token 计数确定（M1 默认）。"""

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        tokens_per_call: int = 100,
        cost_per_call: float = 0.0,
    ) -> None:
        self._responses = responses or {}
        self.tokens_per_call = tokens_per_call
        self.cost_per_call = cost_per_call
        self.call_count = 0

    def chat(
        self, messages: list[dict[str, str]], model: str = "fake", max_tokens: int = 512
    ) -> LLMResponse:
        self.call_count += 1
        key = messages[-1]["content"] if messages else ""
        text = self._responses.get(key, f"[fake:{model}] {key[:40]}")
        output_tokens = min(len(text), max_tokens)
        return LLMResponse(
            text=text,
            input_tokens=self.tokens_per_call,
            output_tokens=output_tokens,
            cost=self.cost_per_call,
        )

    def estimate_cost(self, max_tokens: int) -> float:
        """调用前成本估算（预算预留用）。"""
        return self.cost_per_call


class ModelGateway:
    """预算使用量的唯一权威记账入口（002-A 第二节第 6 条）。"""

    def __init__(
        self,
        provider: LLMProvider,
        budget: BudgetController,
        audit: AuditLog,
        task_id: str,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._audit = audit
        self._task_id = task_id

    def chat(
        self, messages: list[dict[str, str]], model: str = "fake", max_tokens: int = 512
    ) -> LLMResponse:
        # 调用前预算预留：预算不足时不再发起调用（GT-09）；cost 经 Provider 接口估算
        estimated_cost = self._provider.estimate_cost(max_tokens)
        if not self._budget.can_call(
            estimated_input_tokens=max_tokens,
            estimated_output_tokens=max_tokens,
            estimated_cost=estimated_cost,
        ):
            raise BudgetExceeded(
                "precheck", self._budget.usage["tokens"], float(self._budget.token_budget)
            )
        resp = self._provider.chat(messages, model=model, max_tokens=max_tokens)
        self._budget.record(resp.input_tokens, resp.output_tokens, resp.cost)
        self._audit.entry(
            "model_call",
            task_id=self._task_id,
            model=model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost=resp.cost,
        )
        return resp
