"""FakeModelProvider（005 3.3 / 6）：实现生产 Provider 契约的测试基线。

- 自动测试必须使用 Fake（不调用网络、不需要 API Key、可重复、无费用）。
- 保留 chat() 兼容 M1 DeterministicFakeModel 行为（responses/call_count）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.gateway.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderHealth,
    UsageEstimate,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeModelProvider:
    """确定性 Fake Provider：结构化输出由 responses 映射驱动，永不访问网络。"""

    provider_name = "fake"

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        tokens_per_call: int = 128,
        cost_per_call: float = 0.0,
        latency_ms: int = 1,
        health_status: str = "healthy",
    ) -> None:
        self._responses = responses or {}
        self.tokens_per_call = tokens_per_call
        self.cost_per_call = cost_per_call
        self._latency_ms = latency_ms
        self._health_status = health_status
        self.call_count = 0

    # ---- 生产契约（005 6） ----
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        key = request.messages[-1]["content"] if request.messages else ""
        text = self._responses.get(key, f"[fake:{request.model}] {key[:60]}")
        output_tokens = min(len(text) // 4 + 1, request.max_output_tokens)
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=request.model,
            raw_text=text,
            input_tokens=self.tokens_per_call,
            output_tokens=output_tokens,
            total_tokens=self.tokens_per_call + output_tokens,
            estimated_cost=self.cost_per_call,
            latency_ms=self._latency_ms,
            finish_reason="stop",
            provider_request_id=f"fake-{self.call_count}",
            retry_count=0,
        )

    def estimate_usage(self, request: ModelRequest) -> UsageEstimate:
        return UsageEstimate(
            estimated_input_tokens=self.tokens_per_call,
            estimated_max_output_tokens=request.max_output_tokens,
            estimated_max_cost=self.cost_per_call,
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status=self._health_status,
            provider=self.provider_name,
            model="fake",
            message="fake provider always healthy in tests",
            checked_at=_now(),
        )

    # ---- M1 兼容（chat） ----
    def chat(
        self, messages: list[dict[str, str]], model: str = "fake", max_tokens: int = 512
    ) -> ModelResponse:
        """兼容旧 chat 路径：返回 ModelResponse（M1 测试的 chat 语义）。"""
        resp = self.generate(
            ModelRequest(
                request_id="chat-compat",
                task_id="",
                agent_id="",
                role_type="",
                model=model,
                messages=messages,
                max_output_tokens=max_tokens,
            )
        )
        resp.request_id = "chat-compat"
        return resp
