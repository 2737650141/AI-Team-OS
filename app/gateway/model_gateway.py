"""Model Gateway：统一 Provider 接口 + DeterministicFakeModel + 唯一预算记账。"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.core.budget import BudgetController, BudgetExceeded, BudgetSnapshot
from app.core.config import lookup_price
from app.gateway.audit import AuditLog
from app.gateway.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorCode,
    UsageEstimate,
)


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
        provider: object,
        budget: BudgetController,
        audit: AuditLog,
        task_id: str,
        run_id: str | None = None,
    ) -> None:
        self._provider: Any = provider
        self._budget = budget
        self._audit = audit
        self._task_id = task_id
        self._run_id = run_id

    @property
    def budget(self) -> BudgetSnapshot:
        """预算只读视图（006 四.1 LOW 修复）：返回冻结快照，不暴露可变 BudgetController。"""
        return BudgetSnapshot(
            tokens_used=self._budget.usage["tokens"],
            cost_used=self._budget.usage["cost"],
            token_budget=float(self._budget.token_budget),
            cost_budget=float(self._budget.cost_budget),
            calls_used=int(self._budget.usage.get("calls", 0)),
            max_calls=getattr(self._budget, "_max_calls", 30),
        )

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

    # ---- M3-A 生产路径（005 六/十/十一） ----
    def generate(
        self,
        request: ModelRequest,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> ModelResponse:
        """真实模型调用生产路径：预算预留 → 重试 → 实际结算 → 审计。

        - 预算不足不发起请求（10.1/10.4 → budget_insufficient，LLM 不能自行提高预算）。
        - 可重试错误按指数退避（11.3），每次尝试写审计，重试不重置预算。
        - 实际 Usage 结算（10.2），价格未知则 estimated_cost=None。
        - 审计只记录摘要与哈希（6.2），不落 messages 全文。
        """
        sleep_fn = sleep_fn or time.sleep
        provider_name = getattr(
            self._provider, "provider_name", type(self._provider).__name__.lower()
        )
        est = (
            self._provider.estimate_usage(request)
            if hasattr(self._provider, "estimate_usage")
            else UsageEstimate()
        )
        # 价格按集中价格表计算（10.3）：调用前预留最大费用；未知价格不伪造
        if est.estimated_max_cost is None:
            price = lookup_price(provider_name, request.model)
            if price is not None:
                unit = max(price.input_price_per_million, price.output_price_per_million)
                est.estimated_max_cost = (
                    (est.estimated_input_tokens + est.estimated_max_output_tokens) / 1e6 * unit
                )
        if not self._budget.can_call(
            estimated_input_tokens=est.estimated_input_tokens,
            estimated_output_tokens=est.estimated_max_output_tokens,
            estimated_cost=est.estimated_max_cost or 0.0,
        ):
            raise ProviderError(
                ProviderErrorCode.BUDGET_INSUFFICIENT,
                "budget insufficient for model call",
                provider=provider_name,
                model=request.model,
            )
        attempt = 0
        from app.core.events import emit as event_emit

        event_emit(
            task_id=self._task_id,
            run_id=request.run_id or self._run_id,
            event_type="model_call_started",
            actor_type=request.role_type,
            actor_id=request.agent_id,
            summary=f"Calling {request.model}",
            payload_safe={
                "provider": provider_name,
                "model": request.model,
                "role": request.role_type,
                "real_call": provider_name not in {"fake", "legacy", "fake_model"},
            },
        )
        while True:
            try:
                resp = self._call_provider(request, attempt)
                break
            except ProviderError as exc:
                exc.attempt = attempt
                if not exc.retryable or attempt >= max_retries:
                    self._audit.entry(
                        "model_error",
                        task_id=self._task_id,
                        code=exc.code.value,
                        attempt=attempt,
                        model=request.model,
                    )
                    event_emit(
                        task_id=self._task_id,
                        run_id=request.run_id or self._run_id,
                        event_type="agent_failed",
                        actor_type=request.role_type,
                        actor_id=request.agent_id,
                        summary="model call failed",
                        payload_safe={
                            "provider": provider_name,
                            "model": request.model,
                            "failure_class": _acceptance_failure(exc.code),
                            "attempt": attempt,
                        },
                    )
                    raise
                attempt += 1
                delay = min(backoff_base * (2**attempt), backoff_max)
                self._audit.entry(
                    "model_retry",
                    task_id=self._task_id,
                    code=exc.code.value,
                    attempt=attempt,
                    model=request.model,
                )
                sleep_fn(delay)
        # 实际结算（10.2）：按 Provider 返回的 Usage 记账，未使用预留自然释放；
        # 价格未知（estimated_cost=None）时按价格表计算，仍未知则记 0 不伪造费用
        cost = resp.estimated_cost
        if cost is None:
            price = lookup_price(resp.provider, resp.model)
            if price is not None:
                cost = (
                    resp.input_tokens / 1e6 * price.input_price_per_million
                    + resp.output_tokens / 1e6 * price.output_price_per_million
                )
        self._budget.record(resp.input_tokens, resp.output_tokens, cost or 0.0)
        prompt_hash = hashlib.sha256(
            json.dumps(request.messages, ensure_ascii=False, default=str).encode()
        ).hexdigest()[:16]
        self._audit.entry(
            "model_call",
            task_id=self._task_id,
            provider=resp.provider,
            model=resp.model,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            estimated_cost=resp.estimated_cost,
            calculated_cost=cost,
            cost_available=cost is not None,
            total_tokens=resp.total_tokens,
            cached_tokens=resp.cached_tokens,
            usage_available=resp.usage_available,
            prompt_hash=prompt_hash,
            retry_count=resp.retry_count,
            latency_ms=resp.latency_ms,
        )
        event_emit(
            task_id=self._task_id,
            run_id=request.run_id or self._run_id,
            event_type="model_call_completed",
            actor_type=request.role_type,
            actor_id=request.agent_id,
            summary=f"Model completed: {resp.model}",
            payload_safe={
                "provider": resp.provider,
                "model": resp.model,
                "role": request.role_type,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "cached_tokens": resp.cached_tokens,
                "total_tokens": resp.total_tokens,
                "latency_ms": resp.latency_ms,
                "finish_reason": resp.finish_reason,
                "estimated_cost": resp.estimated_cost,
                "calculated_cost": cost,
                "cost_available": cost is not None,
                "usage_available": resp.usage_available,
                "repair_attempts": resp.retry_count,
                "real_call": resp.provider not in {"fake", "legacy", "fake_model"},
            },
        )
        return resp

    def _call_provider(self, request: ModelRequest, attempt: int) -> ModelResponse:
        try:
            if hasattr(self._provider, "generate"):
                resp = self._provider.generate(request)
            else:
                # 兼容旧 Provider（DeterministicFakeModel）：chat 包装为 ModelResponse
                r = self._provider.chat(
                    request.messages, model=request.model, max_tokens=request.max_output_tokens
                )
                resp = ModelResponse(
                    request_id=request.request_id,
                    provider="legacy",
                    model=request.model,
                    raw_text=getattr(r, "text", getattr(r, "raw_text", "")),
                    input_tokens=getattr(r, "input_tokens", 0),
                    output_tokens=getattr(r, "output_tokens", 0),
                    estimated_cost=getattr(r, "cost", getattr(r, "estimated_cost", None)),
                    retry_count=attempt,
                )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                ProviderErrorCode.PROVIDER_INTERNAL_ERROR,
                "provider call failed",
                provider=getattr(self._provider, "provider_name", "unknown"),
                model=request.model,
                attempt=attempt,
            ) from exc
        resp.retry_count = attempt
        return resp


def _acceptance_failure(code: ProviderErrorCode) -> str:
    return {
        ProviderErrorCode.AUTHENTICATION_ERROR: "AUTHENTICATION_FAILED",
        ProviderErrorCode.MODEL_NOT_FOUND: "MODEL_NOT_FOUND",
        ProviderErrorCode.RATE_LIMITED: "RATE_LIMITED",
        ProviderErrorCode.TIMEOUT: "PROVIDER_TIMEOUT",
        ProviderErrorCode.PROVIDER_INTERNAL_ERROR: "PROVIDER_SERVER_ERROR",
        ProviderErrorCode.SCHEMA_VALIDATION_FAILED: "SCHEMA_INVALID",
        ProviderErrorCode.BUDGET_INSUFFICIENT: "BUDGET_EXCEEDED",
    }.get(code, "RUNTIME_FAILED")
