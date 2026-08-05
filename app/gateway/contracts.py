"""Model Provider 契约（005 六）：ModelRequest / ModelResponse / ProviderError / ProviderHealth。

- ModelRequest 不得包含 API Key（6.1）。
- ProviderError 的 safe_message 不得携带服务端原始响应（6.3）。
- raw_text 仅受控调试模式短期保留；默认审计只记摘要与哈希（6.2）。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    request_id: str
    task_id: str
    run_id: str | None = None
    agent_id: str
    role_type: str
    model: str
    messages: list[dict[str, str]] = Field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    temperature: float = 0.0
    max_output_tokens: int = 4096
    timeout_seconds: int = 60
    metadata: dict[str, Any] = Field(default_factory=dict)
    # 注意：无 API Key 字段（005 6.1）


class ModelResponse(BaseModel):
    request_id: str
    provider: str
    model: str
    raw_text: str | None = None  # 仅受控调试模式短期保留
    structured_output: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float | None = None
    latency_ms: int = 0
    finish_reason: str | None = None
    provider_request_id: str | None = None
    retry_count: int = 0


class ProviderErrorCode(str, Enum):
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_ERROR = "permission_error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    INVALID_REQUEST = "invalid_request"
    MODEL_NOT_FOUND = "model_not_found"
    CONTEXT_LENGTH_EXCEEDED = "context_length_exceeded"
    MALFORMED_RESPONSE = "malformed_response"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    PROVIDER_INTERNAL_ERROR = "provider_internal_error"
    BUDGET_INSUFFICIENT = "budget_insufficient"
    CANCELLED = "cancelled"
    CONFIG_ERROR = "config_error"  # 未启用真实调用/缺 API Key/Base URL 非法（005 7.4）


# 可重试错误（005 11.1）
RETRYABLE_CODES = {
    ProviderErrorCode.RATE_LIMITED,
    ProviderErrorCode.TIMEOUT,
    ProviderErrorCode.CONNECTION_ERROR,
    ProviderErrorCode.PROVIDER_INTERNAL_ERROR,
}

# 不可重试错误（005 11.2）
NON_RETRYABLE_CODES = {
    ProviderErrorCode.AUTHENTICATION_ERROR,
    ProviderErrorCode.PERMISSION_ERROR,
    ProviderErrorCode.INVALID_REQUEST,
    ProviderErrorCode.MODEL_NOT_FOUND,
    ProviderErrorCode.BUDGET_INSUFFICIENT,
    ProviderErrorCode.CONFIG_ERROR,
    ProviderErrorCode.SCHEMA_VALIDATION_FAILED,
    ProviderErrorCode.CANCELLED,
}


class ProviderError(Exception):
    """分类错误（005 6.3）。safe_message 可安全返回用户，不得包含服务端原始响应。"""

    def __init__(
        self,
        code: ProviderErrorCode,
        safe_message: str,
        provider: str = "",
        model: str = "",
        attempt: int = 0,
        retryable: bool | None = None,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.provider = provider
        self.model = model
        self.attempt = attempt
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
        super().__init__(f"[{code.value}] {safe_message}")


class ProviderHealth(BaseModel):
    status: str  # healthy | degraded | unavailable | misconfigured | disabled（005 十二）
    provider: str
    model: str
    message: str = ""
    checked_at: str = ""


class UsageEstimate(BaseModel):
    estimated_input_tokens: int = 0
    estimated_max_output_tokens: int = 0
    estimated_max_cost: float | None = None  # 价格未知时为 None（005 10.3）


class ModelProvider(Protocol):
    """生产 Provider 接口（005 6）。"""

    def generate(self, request: ModelRequest) -> ModelResponse: ...

    def estimate_usage(self, request: ModelRequest) -> UsageEstimate: ...

    def health_check(self) -> ProviderHealth: ...
