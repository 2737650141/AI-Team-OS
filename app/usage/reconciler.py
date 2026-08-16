"""Normalize provider usage without double-counting overlapping token categories."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from app.gateway.contracts import ModelRequest, ModelResponse, UsageEstimate
from app.usage.models import CostSource, NormalizedModelUsage, UsageSource


def _number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


class UsageReconciler:
    """Provider semantics terminate here; business code consumes one stable schema.

    OpenAI/DeepSeek-compatible cached input is a subset of input, and reasoning is a
    subset of output. Anthropic cache creation/read tokens are input categories and
    are added to uncached ``input_tokens`` for the normalized inclusive input total.
    """

    @staticmethod
    def openai_usage(usage: Mapping[str, Any]) -> dict[str, int | None]:
        prompt = _number(usage.get("prompt_tokens"))
        output = _number(usage.get("completion_tokens"))
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        cached = _number(usage.get("prompt_cache_hit_tokens"))
        if cached is None:
            cached = _number(prompt_details.get("cached_tokens"))
        reasoning = _number(completion_details.get("reasoning_tokens"))
        total = _number(usage.get("total_tokens"))
        if total is None and prompt is not None and output is not None:
            total = prompt + output
        return {
            "input_tokens": prompt,
            "output_tokens": output,
            "reasoning_tokens": reasoning,
            "cached_input_tokens": cached,
            "cache_write_tokens": None,
            "other_tokens": None,
            "total_tokens": total,
        }

    deepseek_usage = openai_usage
    custom_compatible_usage = openai_usage

    @staticmethod
    def anthropic_usage(usage: Mapping[str, Any]) -> dict[str, int | None]:
        uncached = _number(usage.get("input_tokens"))
        cache_read = _number(usage.get("cache_read_input_tokens"))
        cache_write = _number(usage.get("cache_creation_input_tokens"))
        output = _number(usage.get("output_tokens"))
        if uncached is None:
            inclusive_input = None
        else:
            inclusive_input = uncached + (cache_read or 0) + (cache_write or 0)
        total = (
            inclusive_input + output if inclusive_input is not None and output is not None else None
        )
        return {
            "input_tokens": inclusive_input,
            "output_tokens": output,
            "reasoning_tokens": None,
            "cached_input_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "other_tokens": None,
            "total_tokens": total,
        }

    @classmethod
    def response(
        cls,
        request: ModelRequest,
        response: ModelResponse,
        estimate: UsageEstimate,
        *,
        cost_total: float | None,
        cost_input: float | None = None,
        cost_output: float | None = None,
        cost_source: CostSource = CostSource.UNAVAILABLE,
        context_limit: int | None = None,
        compression: Mapping[str, Any] | None = None,
    ) -> NormalizedModelUsage:
        source = UsageSource(response.usage_source)
        # Missing values remain NULL. An unavailable provider must never become a row of zeros.
        input_tokens = response.input_tokens if response.input_tokens is not None else None
        output_tokens = response.output_tokens if response.output_tokens is not None else None
        total = response.total_tokens if response.total_tokens is not None else None
        if total is None and input_tokens is not None and output_tokens is not None:
            total = input_tokens + output_tokens
        compression = compression or {}
        return NormalizedModelUsage(
            usage_id=uuid.uuid4().hex,
            scope=str(request.metadata.get("scope") or "user_task"),
            task_id=request.task_id,
            run_id=request.run_id,
            call_id=request.request_id,
            role=request.role_type,
            agent_id=request.agent_id,
            provider_id=str(
                response.provider_id
                or request.metadata.get("provider_id")
                or response.provider
            ),
            provider_name=response.provider,
            model_id=response.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=response.reasoning_tokens,
            cached_input_tokens=response.cached_input_tokens,
            cache_miss_tokens=response.cache_miss_tokens,
            cache_write_tokens=response.cache_write_tokens,
            other_tokens=response.other_tokens,
            total_tokens=total,
            usage_source=source,
            estimated_input_tokens=estimate.estimated_input_tokens,
            estimated_output_tokens=estimate.estimated_max_output_tokens,
            context_tokens_before=input_tokens,
            context_tokens_after=total,
            context_limit=context_limit,
            compression_triggered=bool(compression.get("triggered", False)),
            compression_tokens_before=_number(compression.get("before")),
            compression_tokens_after=_number(compression.get("after")),
            latency_ms=response.latency_ms,
            cost_input=cost_input,
            cost_output=cost_output,
            cost_total=cost_total,
            currency="USD" if cost_total is not None else None,
            cost_source=cost_source,
        )
