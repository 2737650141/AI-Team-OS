from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class UsageSource(StrEnum):
    REPORTED = "REPORTED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class CostSource(StrEnum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    PRICE_TABLE = "PRICE_TABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ContextStatus(StrEnum):
    AMPLE = "AMPLE"
    MODERATE = "MODERATE"
    NEAR_COMPACTION = "NEAR_COMPACTION"
    COMPACTION_REQUIRED = "COMPACTION_REQUIRED"
    UNKNOWN = "UNKNOWN"


class CapabilitySource(StrEnum):
    PROVIDER_METADATA = "PROVIDER_METADATA"
    OFFICIAL_ADAPTER = "OFFICIAL_ADAPTER"
    USER_CONFIGURED = "USER_CONFIGURED"
    VERIFIED_MODEL_PROFILE = "VERIFIED_MODEL_PROFILE"


class NormalizedModelUsage(BaseModel):
    usage_id: str
    task_id: str
    run_id: str | None = None
    call_id: str
    role: str
    agent_id: str
    provider_id: str
    provider_name: str
    model_id: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    other_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    usage_source: UsageSource
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    estimated_output_tokens: int | None = Field(default=None, ge=0)
    context_tokens_before: int | None = Field(default=None, ge=0)
    context_tokens_after: int | None = Field(default=None, ge=0)
    context_limit: int | None = Field(default=None, gt=0)
    compression_triggered: bool = False
    compression_tokens_before: int | None = Field(default=None, ge=0)
    compression_tokens_after: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    cost_input: float | None = Field(default=None, ge=0)
    cost_output: float | None = Field(default=None, ge=0)
    cost_total: float | None = Field(default=None, ge=0)
    currency: str | None = None
    cost_source: CostSource = CostSource.UNAVAILABLE
    timestamp: str = Field(default_factory=utc_now)


class ModelCapability(BaseModel):
    provider_id: str
    model_id: str
    context_window: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    tokenizer: str | None = None
    usage_reporting: bool | None = None
    reasoning_usage_reporting: bool | None = None
    cache_usage_reporting: bool | None = None
    source: CapabilitySource
    updated_at: str = Field(default_factory=utc_now)


VERIFIED_MODEL_PROFILES: dict[tuple[str, str], ModelCapability] = {
    ("DeepSeek Official", "deepseek-v4-flash"): ModelCapability(
        provider_id="DeepSeek Official",
        model_id="deepseek-v4-flash",
        context_window=1_000_000,
        max_output_tokens=384_000,
        usage_reporting=True,
        reasoning_usage_reporting=True,
        cache_usage_reporting=True,
        source=CapabilitySource.VERIFIED_MODEL_PROFILE,
    ),
}


def verified_model_profile(provider: str, model: str) -> ModelCapability | None:
    profile = VERIFIED_MODEL_PROFILES.get((provider, model))
    return profile.model_copy(deep=True) if profile else None
