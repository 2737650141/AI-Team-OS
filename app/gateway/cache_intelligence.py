"""Privacy-minimal, provider-agnostic prompt-cache diagnostics.

This module never stores prompt text or rewrites request messages.  It canonicalizes
only transient diagnostic representations, records hashes/sizes, and lets existing
provider adapters opt into a cache directive only after capability evidence exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from app.gateway.contracts import ModelRequest, ModelResponse

CACHE_TELEMETRY_FIELDS = frozenset(
    {
        "provider_id",
        "protocol_family",
        "model_id",
        "model_family",
        "lineage_hash",
        "system_hash",
        "tools_hash",
        "stable_context_hash",
        "prefix_hash",
        "prefix_bytes",
        "estimated_prefix_tokens",
        "timestamp",
        "volatile_prefix_reasons",
        "status",
        "reasons",
        "first_changed_section",
        "first_changed_offset",
        "endpoint_family",
        "endpoint_fingerprint",
        "prompt_cache_mode",
        "supports_cache_control",
        "supports_prompt_cache_key",
        "supports_cache_retention",
        "reports_cache_hit",
        "reports_cache_miss",
        "reports_cached_input",
        "reports_cache_write",
        "source",
        "confidence",
        "strategy",
        "applied",
        "reason",
        "provider_cache_availability",
        "provider_cache_hit_tokens",
        "provider_cache_miss_tokens",
        "provider_cache_write_tokens",
        "provider_cached_input_tokens",
        "provider_cache_hit_ratio",
        "coalesce_eligible",
        "privacy",
    }
)


def safe_cache_telemetry(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one privacy contract across response, audit, event, and storage sinks."""
    safe: dict[str, Any] = {}
    for key, value in observation.items():
        if key not in CACHE_TELEMETRY_FIELDS:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            safe[key] = value[:32]
    return safe


class ProtocolFamily(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    OPENAI_RESPONSES = "openai_responses"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    LOCAL = "local"
    UNKNOWN = "unknown"


class EndpointFamily(StrEnum):
    DEEPSEEK_OFFICIAL = "deepseek_official"
    OPENAI_OFFICIAL = "openai_official"
    ANTHROPIC_OFFICIAL = "anthropic_official"
    THIRD_PARTY = "third_party"
    LOCAL = "local"
    UNKNOWN = "unknown"


class PromptCacheMode(StrEnum):
    AUTOMATIC = "automatic"
    CACHE_CONTROL = "cache_control"
    PROMPT_CACHE_KEY = "prompt_cache_key"
    PASSIVE = "passive"
    UNKNOWN = "unknown"


class CapabilitySource(StrEnum):
    OFFICIAL_PROFILE = "OFFICIAL_PROFILE"
    OBSERVED = "OBSERVED"
    USER_CONFIGURED = "USER_CONFIGURED"
    UNKNOWN = "UNKNOWN"


class CapabilityConfidence(StrEnum):
    VERIFIED = "VERIFIED"
    OBSERVED = "OBSERVED"
    ASSUMED = "ASSUMED"
    UNKNOWN = "UNKNOWN"


class DriftStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    STABLE = "STABLE"
    DRIFT = "DRIFT"


class DriftReason(StrEnum):
    SYSTEM_CHANGED = "SYSTEM_CHANGED"
    TOOLS_CHANGED = "TOOLS_CHANGED"
    TOOL_SCHEMA_CHANGED = "TOOL_SCHEMA_CHANGED"
    STABLE_CONTEXT_CHANGED = "STABLE_CONTEXT_CHANGED"
    VOLATILE_PREFIX = "VOLATILE_PREFIX"
    UNKNOWN = "UNKNOWN"


class CacheAvailability(StrEnum):
    REPORTED = "REPORTED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ProviderIdentity:
    """Runtime provider identity; only the fingerprint is emitted or persisted."""

    provider_id: str
    provider_name: str
    endpoint: str | None
    endpoint_fingerprint: str | None
    endpoint_family: EndpointFamily
    protocol_family: ProtocolFamily
    selected_model: str | None = None
    adapter_capabilities: frozenset[str] = frozenset()

    def telemetry(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "endpoint_family": self.endpoint_family.value,
            "protocol_family": self.protocol_family.value,
            "selected_model": self.selected_model,
            "adapter_capabilities": sorted(self.adapter_capabilities),
        }


@dataclass(frozen=True)
class ProviderCapabilityProfile:
    provider_id: str
    endpoint_family: EndpointFamily
    endpoint_fingerprint: str | None
    protocol_family: ProtocolFamily
    model_id: str
    model_family: str
    prompt_cache_mode: PromptCacheMode
    supports_cache_control: bool | None
    supports_prompt_cache_key: bool | None
    supports_cache_retention: bool | None
    reports_cache_hit: bool | None
    reports_cache_miss: bool | None
    reports_cached_input: bool | None
    reports_cache_write: bool | None
    source: CapabilitySource
    confidence: CapabilityConfidence

    def telemetry(self) -> dict[str, Any]:
        return {
            "endpoint_family": self.endpoint_family.value,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "protocol_family": self.protocol_family.value,
            "model_family": self.model_family,
            "prompt_cache_mode": self.prompt_cache_mode.value,
            "supports_cache_control": self.supports_cache_control,
            "supports_prompt_cache_key": self.supports_prompt_cache_key,
            "supports_cache_retention": self.supports_cache_retention,
            "reports_cache_hit": self.reports_cache_hit,
            "reports_cache_miss": self.reports_cache_miss,
            "reports_cached_input": self.reports_cached_input,
            "reports_cache_write": self.reports_cache_write,
            "source": self.source.value,
            "confidence": self.confidence.value,
        }


@dataclass(frozen=True)
class VolatileFinding:
    code: str
    section: str


@dataclass(frozen=True)
class PrefixShape:
    provider_id: str
    protocol_family: str
    model_id: str
    model_family: str
    lineage_hash: str
    system_hash: str
    tools_hash: str
    tool_names_hash: str
    stable_context_hash: str
    prefix_hash: str
    prefix_bytes: int
    estimated_prefix_tokens: int
    timestamp: str
    volatile_findings: tuple[VolatileFinding, ...] = ()

    def telemetry(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "protocol_family": self.protocol_family,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "lineage_hash": self.lineage_hash,
            "system_hash": self.system_hash,
            "tools_hash": self.tools_hash,
            "stable_context_hash": self.stable_context_hash,
            "prefix_hash": self.prefix_hash,
            "prefix_bytes": self.prefix_bytes,
            "estimated_prefix_tokens": self.estimated_prefix_tokens,
            "timestamp": self.timestamp,
            "volatile_prefix_reasons": [finding.code for finding in self.volatile_findings],
        }


@dataclass(frozen=True)
class PrefixDrift:
    status: DriftStatus
    reasons: tuple[DriftReason, ...]
    first_changed_section: str | None = None
    first_changed_offset: int | None = None

    def telemetry(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reasons": [reason.value for reason in self.reasons],
            "first_changed_section": self.first_changed_section,
            "first_changed_offset": self.first_changed_offset,
        }


@dataclass(frozen=True)
class StableEnvironmentSnapshot:
    """Hash-only environment baseline. Relocation is deliberately not enabled."""

    fingerprint: str
    bytes: int
    volatile_findings: tuple[VolatileFinding, ...] = ()

    @classmethod
    def from_values(cls, values: Mapping[str, Any]) -> StableEnvironmentSnapshot:
        payload = canonical_json_bytes(values)
        findings = tuple(_volatile_findings("environment", values, {}))
        return cls(
            fingerprint=_sha256(payload),
            bytes=len(payload),
            volatile_findings=findings,
        )


@dataclass(frozen=True)
class EnvironmentDelta:
    baseline_fingerprint: str | None
    current_fingerprint: str
    changed_keys: tuple[str, ...]
    relocation_safe: bool = False


def environment_delta(
    baseline: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> EnvironmentDelta:
    current_payload = canonical_json_bytes(current)
    if baseline is None:
        return EnvironmentDelta(None, _sha256(current_payload), tuple(sorted(map(str, current))))
    previous_payload = canonical_json_bytes(baseline)
    keys = set(map(str, baseline)) | set(map(str, current))
    changed = tuple(
        key
        for key in sorted(keys)
        if canonical_json_bytes(baseline.get(key)) != canonical_json_bytes(current.get(key))
    )
    return EnvironmentDelta(_sha256(previous_payload), _sha256(current_payload), changed)


def canonicalize_json(value: Any) -> Any:
    """Recursively canonicalize JSON objects without changing array semantics."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize_json(item) for item in value]
    if isinstance(value, set):
        return sorted((canonicalize_json(item) for item in value), key=_canonical_sort_key)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        canonicalize_json(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_schema_fingerprint(schema: Any) -> str:
    return _sha256(canonical_json_bytes(schema))


def canonicalize_tools(tools: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Sort only the outer tool collection; preserve every schema array order."""

    normalized: list[tuple[str, str, dict[str, Any]]] = []
    for raw in tools or ():
        tool = dict(raw)
        function = tool.get("function")
        if isinstance(function, Mapping):
            name = str(function.get("name") or tool.get("name") or "")
            schema = function.get("parameters", function.get("schema", {}))
        else:
            name = str(tool.get("name") or "")
            schema = tool.get("schema", tool.get("parameters", tool.get("input_schema", {})))
        fingerprint = canonical_schema_fingerprint(schema)
        normalized.append(
            (
                name,
                fingerprint,
                {
                    "name": name,
                    "schema": canonicalize_json(schema),
                    "schema_fingerprint": fingerprint,
                },
            )
        )
    normalized.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in normalized]


class CanonicalRequestPipeline:
    """Derives hash-only prefix shapes from an already-built final request."""

    def build(self, request: ModelRequest, identity: ProviderIdentity) -> PrefixShape:
        systems: list[dict[str, str]] = []
        for message in request.messages:
            if message.get("role") != "system":
                break
            systems.append(
                {
                    "role": str(message.get("role", "")),
                    "content": str(message.get("content", "")),
                }
            )
        raw_tools = (
            request.metadata.get("cache_tools")
            or request.metadata.get("provider_tools")
            or []
        )
        tools = canonicalize_tools(
            raw_tools
            if isinstance(raw_tools, Sequence)
            and not isinstance(raw_tools, (str, bytes, bytearray))
            else []
        )
        stable_context: dict[str, Any] = {
            "response_schema": request.response_schema or {},
        }
        metadata_context = request.metadata.get("cache_stable_context")
        if isinstance(metadata_context, Mapping):
            stable_context["contract"] = metadata_context
        prompt_id = request.metadata.get("prompt_id")
        prompt_version = request.metadata.get("prompt_version")
        if prompt_id:
            stable_context["prompt_id"] = str(prompt_id)
        if prompt_version:
            stable_context["prompt_version"] = str(prompt_version)

        system_payload = canonical_json_bytes(systems)
        tools_payload = canonical_json_bytes(tools)
        stable_context_payload = canonical_json_bytes(stable_context)
        tool_names_payload = canonical_json_bytes([tool["name"] for tool in tools])
        prefix_payload = canonical_json_bytes(
            {
                "provider_id": identity.provider_id,
                "protocol_family": identity.protocol_family.value,
                "model_id": request.model,
                "system": systems,
                "tools": tools,
                "stable_context": stable_context,
            }
        )
        sections = {
            "system": systems,
            "tools": tools,
            "stable_context": stable_context,
        }
        dynamic_values = {
            "request_id": request.request_id,
            "task_id": request.task_id,
            "run_id": request.run_id or "",
        }
        findings = tuple(
            finding
            for section, value in sections.items()
            for finding in _volatile_findings(section, value, dynamic_values)
        )
        lineage = canonical_json_bytes(
            {
                "provider_id": identity.provider_id,
                "protocol_family": identity.protocol_family.value,
                "model_id": request.model,
                "role": request.role_type,
                "session": request.run_id or request.task_id,
            }
        )
        return PrefixShape(
            provider_id=identity.provider_id,
            protocol_family=identity.protocol_family.value,
            model_id=request.model,
            model_family=_model_family(request.model),
            lineage_hash=_sha256(lineage),
            system_hash=_sha256(system_payload),
            tools_hash=_sha256(tools_payload),
            tool_names_hash=_sha256(tool_names_payload),
            stable_context_hash=_sha256(stable_context_payload),
            prefix_hash=_sha256(prefix_payload),
            prefix_bytes=len(prefix_payload),
            estimated_prefix_tokens=math.ceil(len(prefix_payload) / 4),
            timestamp=_utc_now(),
            volatile_findings=findings,
        )


class PrefixDriftDetector:
    """Retains only prior hashes, never prior prompt or canonical payload bytes."""

    def __init__(self) -> None:
        self._previous: dict[str, PrefixShape] = {}

    def observe(self, shape: PrefixShape) -> PrefixDrift:
        previous = self._previous.get(shape.lineage_hash)
        self._previous[shape.lineage_hash] = shape
        volatile = bool(shape.volatile_findings)
        if previous is None:
            if volatile:
                return PrefixDrift(
                    DriftStatus.DRIFT,
                    (DriftReason.VOLATILE_PREFIX,),
                    shape.volatile_findings[0].section,
                )
            return PrefixDrift(DriftStatus.UNKNOWN, (DriftReason.UNKNOWN,))

        reasons: list[DriftReason] = []
        section: str | None = None
        if previous.system_hash != shape.system_hash:
            reasons.append(DriftReason.SYSTEM_CHANGED)
            section = "system"
        if previous.tools_hash != shape.tools_hash:
            reasons.append(
                DriftReason.TOOL_SCHEMA_CHANGED
                if previous.tool_names_hash == shape.tool_names_hash
                else DriftReason.TOOLS_CHANGED
            )
            section = section or "tools"
        if previous.stable_context_hash != shape.stable_context_hash:
            reasons.append(DriftReason.STABLE_CONTEXT_CHANGED)
            section = section or "stable_context"
        if volatile:
            reasons.append(DriftReason.VOLATILE_PREFIX)
            section = section or shape.volatile_findings[0].section
        if not reasons and previous.prefix_hash != shape.prefix_hash:
            reasons.append(DriftReason.UNKNOWN)
        if reasons:
            return PrefixDrift(DriftStatus.DRIFT, tuple(reasons), section)
        return PrefixDrift(DriftStatus.STABLE, ())


class ProviderCapabilityResolver:
    """Conservative profiles keyed by endpoint/protocol, never model-name branding."""

    def __init__(self) -> None:
        self._observed: dict[tuple[str, str | None, str, str], ProviderCapabilityProfile] = {}

    def resolve(
        self,
        identity: ProviderIdentity,
        model_id: str,
        user_config: Mapping[str, Any] | None = None,
    ) -> ProviderCapabilityProfile:
        base = self._official_profile(identity, model_id) or self._unknown_profile(
            identity, model_id
        )
        if user_config:
            return self._configured_profile(base, user_config)
        observed = self._observed.get(self._key(identity, model_id))
        return observed or base

    def observe(
        self,
        identity: ProviderIdentity,
        model_id: str,
        profile: ProviderCapabilityProfile,
        response: ModelResponse,
    ) -> ProviderCapabilityProfile:
        if profile.source is CapabilitySource.USER_CONFIGURED:
            return profile
        positive_cached = (
            response.cached_input_tokens is not None or response.cached_tokens is not None
        )
        positive_miss = response.cache_miss_tokens is not None
        positive_write = response.cache_write_tokens is not None
        if not positive_cached and not positive_miss and not positive_write:
            return profile
        fields: dict[str, Any] = {
            "reports_cache_hit": True if positive_cached else profile.reports_cache_hit,
            "reports_cache_miss": True if positive_miss else profile.reports_cache_miss,
            "reports_cached_input": True if positive_cached else profile.reports_cached_input,
            "reports_cache_write": True if positive_write else profile.reports_cache_write,
        }
        if profile.source is CapabilitySource.UNKNOWN:
            fields.update(
                source=CapabilitySource.OBSERVED,
                confidence=CapabilityConfidence.OBSERVED,
            )
        observed = replace(profile, **fields)
        self._observed[self._key(identity, model_id)] = observed
        return observed

    @staticmethod
    def _key(identity: ProviderIdentity, model_id: str) -> tuple[str, str | None, str, str]:
        return (
            identity.provider_id,
            identity.endpoint_fingerprint,
            identity.protocol_family.value,
            model_id,
        )

    def _official_profile(
        self, identity: ProviderIdentity, model_id: str
    ) -> ProviderCapabilityProfile | None:
        common = {
            "provider_id": identity.provider_id,
            "endpoint_family": identity.endpoint_family,
            "endpoint_fingerprint": identity.endpoint_fingerprint,
            "protocol_family": identity.protocol_family,
            "model_id": model_id,
            "model_family": _model_family(model_id),
            "source": CapabilitySource.OFFICIAL_PROFILE,
            "confidence": CapabilityConfidence.VERIFIED,
        }
        if (
            identity.endpoint_family is EndpointFamily.DEEPSEEK_OFFICIAL
            and identity.protocol_family is ProtocolFamily.OPENAI_CHAT_COMPLETIONS
        ):
            return ProviderCapabilityProfile(
                **common,
                prompt_cache_mode=PromptCacheMode.AUTOMATIC,
                supports_cache_control=False,
                supports_prompt_cache_key=False,
                supports_cache_retention=None,
                reports_cache_hit=True,
                reports_cache_miss=None,
                reports_cached_input=True,
                reports_cache_write=None,
            )
        if (
            identity.endpoint_family is EndpointFamily.OPENAI_OFFICIAL
            and identity.protocol_family
            in {ProtocolFamily.OPENAI_CHAT_COMPLETIONS, ProtocolFamily.OPENAI_RESPONSES}
        ):
            return ProviderCapabilityProfile(
                **common,
                prompt_cache_mode=PromptCacheMode.AUTOMATIC,
                supports_cache_control=False,
                # The current adapter is Chat Completions-only and has no verified
                # prompt_cache_key contract, so this remains unknown instead of guessed.
                supports_prompt_cache_key=None,
                supports_cache_retention=None,
                reports_cache_hit=True,
                reports_cache_miss=None,
                reports_cached_input=True,
                reports_cache_write=None,
            )
        if (
            identity.endpoint_family is EndpointFamily.ANTHROPIC_OFFICIAL
            and identity.protocol_family is ProtocolFamily.ANTHROPIC_MESSAGES
        ):
            return ProviderCapabilityProfile(
                **common,
                prompt_cache_mode=PromptCacheMode.CACHE_CONTROL,
                supports_cache_control=True,
                supports_prompt_cache_key=False,
                supports_cache_retention=True,
                reports_cache_hit=True,
                reports_cache_miss=True,
                reports_cached_input=True,
                reports_cache_write=True,
            )
        return None

    @staticmethod
    def _unknown_profile(
        identity: ProviderIdentity, model_id: str
    ) -> ProviderCapabilityProfile:
        return ProviderCapabilityProfile(
            provider_id=identity.provider_id,
            endpoint_family=identity.endpoint_family,
            endpoint_fingerprint=identity.endpoint_fingerprint,
            protocol_family=identity.protocol_family,
            model_id=model_id,
            model_family=_model_family(model_id),
            prompt_cache_mode=PromptCacheMode.PASSIVE,
            supports_cache_control=None,
            supports_prompt_cache_key=None,
            supports_cache_retention=None,
            reports_cache_hit=None,
            reports_cache_miss=None,
            reports_cached_input=None,
            reports_cache_write=None,
            source=CapabilitySource.UNKNOWN,
            confidence=CapabilityConfidence.UNKNOWN,
        )

    @staticmethod
    def _configured_profile(
        base: ProviderCapabilityProfile, config: Mapping[str, Any]
    ) -> ProviderCapabilityProfile:
        values: dict[str, Any] = {}
        for name in (
            "supports_cache_control",
            "supports_prompt_cache_key",
            "supports_cache_retention",
            "reports_cache_hit",
            "reports_cache_miss",
            "reports_cached_input",
            "reports_cache_write",
        ):
            if name in config and isinstance(config[name], bool):
                values[name] = config[name]
        if "prompt_cache_mode" in config:
            try:
                values["prompt_cache_mode"] = PromptCacheMode(str(config["prompt_cache_mode"]))
            except ValueError:
                pass
        values["source"] = CapabilitySource.USER_CONFIGURED
        values["confidence"] = CapabilityConfidence.VERIFIED
        if values.get("supports_prompt_cache_key") is True:
            values.setdefault("prompt_cache_mode", PromptCacheMode.PROMPT_CACHE_KEY)
        return replace(base, **values)


@dataclass(frozen=True)
class CacheStrategyApplication:
    strategy: str
    applied: bool
    reason: str
    provider_payload: dict[str, Any] = field(default_factory=dict)

    def telemetry(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "applied": self.applied,
            "reason": self.reason,
        }


class ProviderCacheStrategy:
    name = "passive"

    def apply(
        self,
        request: ModelRequest,
        identity: ProviderIdentity,
        profile: ProviderCapabilityProfile,
        shape: PrefixShape,
    ) -> CacheStrategyApplication:
        del request, identity, profile, shape
        return CacheStrategyApplication(self.name, False, "cache_capability_unavailable")


class DeepSeekCacheStrategy(ProviderCacheStrategy):
    name = "deepseek"

    def apply(
        self,
        request: ModelRequest,
        identity: ProviderIdentity,
        profile: ProviderCapabilityProfile,
        shape: PrefixShape,
    ) -> CacheStrategyApplication:
        del request, identity, profile, shape
        return CacheStrategyApplication(self.name, False, "server_managed_prefix_cache")


class AnthropicCacheStrategy(ProviderCacheStrategy):
    name = "anthropic"

    def apply(
        self,
        request: ModelRequest,
        identity: ProviderIdentity,
        profile: ProviderCapabilityProfile,
        shape: PrefixShape,
    ) -> CacheStrategyApplication:
        del shape
        if profile.supports_cache_control is not True:
            return CacheStrategyApplication(self.name, False, "cache_control_not_confirmed")
        if "cache_control" not in identity.adapter_capabilities:
            return CacheStrategyApplication(self.name, False, "adapter_cache_control_unavailable")
        configured = request.metadata.get("provider_cache_control")
        cache_control = configured if isinstance(configured, Mapping) else {"type": "ephemeral"}
        return CacheStrategyApplication(
            self.name,
            True,
            "confirmed_cache_control",
            {"cache_control": canonicalize_json(cache_control)},
        )


class OpenAICacheStrategy(ProviderCacheStrategy):
    name = "openai"

    def apply(
        self,
        request: ModelRequest,
        identity: ProviderIdentity,
        profile: ProviderCapabilityProfile,
        shape: PrefixShape,
    ) -> CacheStrategyApplication:
        del shape
        explicit_key = request.metadata.get("cache_prompt_key")
        if profile.supports_prompt_cache_key is not True:
            return CacheStrategyApplication(self.name, False, "prompt_cache_key_not_confirmed")
        if "prompt_cache_key" not in identity.adapter_capabilities:
            return CacheStrategyApplication(
                self.name, False, "adapter_prompt_cache_key_unavailable"
            )
        if not isinstance(explicit_key, str) or not _safe_cache_key(explicit_key):
            return CacheStrategyApplication(self.name, False, "explicit_prompt_cache_key_required")
        return CacheStrategyApplication(
            self.name,
            True,
            "user_configured_prompt_cache_key",
            {"prompt_cache_key": explicit_key},
        )


class GenericCompatibleCacheStrategy(OpenAICacheStrategy):
    name = "generic_compatible"


class PassiveCacheStrategy(ProviderCacheStrategy):
    name = "passive"


class CacheStrategyRegistry:
    def __init__(self) -> None:
        self.deepseek = DeepSeekCacheStrategy()
        self.anthropic = AnthropicCacheStrategy()
        self.openai = OpenAICacheStrategy()
        self.generic = GenericCompatibleCacheStrategy()
        self.passive = PassiveCacheStrategy()

    def select(self, profile: ProviderCapabilityProfile) -> ProviderCacheStrategy:
        if profile.endpoint_family is EndpointFamily.DEEPSEEK_OFFICIAL:
            return self.deepseek
        if profile.endpoint_family is EndpointFamily.OPENAI_OFFICIAL:
            return self.openai
        if profile.endpoint_family is EndpointFamily.ANTHROPIC_OFFICIAL:
            return self.anthropic
        if (
            profile.protocol_family is ProtocolFamily.ANTHROPIC_MESSAGES
            and profile.source is not CapabilitySource.UNKNOWN
        ):
            return self.anthropic
        if (
            profile.protocol_family
            in {ProtocolFamily.OPENAI_CHAT_COMPLETIONS, ProtocolFamily.OPENAI_RESPONSES}
            and profile.source is not CapabilitySource.UNKNOWN
        ):
            return self.generic
        return self.passive


@dataclass(frozen=True)
class CacheDoctorObservation:
    shape: PrefixShape
    drift: PrefixDrift
    profile: ProviderCapabilityProfile
    strategy: CacheStrategyApplication
    provider_cache_availability: CacheAvailability
    cache_hit_tokens: int | None
    cache_miss_tokens: int | None
    cache_write_tokens: int | None
    cached_input_tokens: int | None
    provider_cache_hit_ratio: float | None
    coalesce_eligible: bool

    def telemetry(self) -> dict[str, Any]:
        result = {
            **self.shape.telemetry(),
            **self.drift.telemetry(),
            **self.profile.telemetry(),
            **self.strategy.telemetry(),
            "provider_cache_availability": self.provider_cache_availability.value,
            "provider_cache_hit_tokens": self.cache_hit_tokens,
            "provider_cache_miss_tokens": self.cache_miss_tokens,
            "provider_cache_write_tokens": self.cache_write_tokens,
            "provider_cached_input_tokens": self.cached_input_tokens,
            "provider_cache_hit_ratio": self.provider_cache_hit_ratio,
            "coalesce_eligible": self.coalesce_eligible,
            "privacy": "HASHES_AND_SIZES_ONLY",
        }
        return result


@dataclass(frozen=True)
class CachePreparation:
    provider: Any
    request: ModelRequest
    identity: ProviderIdentity
    shape: PrefixShape
    drift: PrefixDrift
    profile: ProviderCapabilityProfile
    strategy: CacheStrategyApplication
    coalesce_eligible: bool


class ColdAnchorCoalescingAdvisor:
    """Experimental eligibility detector. It never waits, batches, or shares calls."""

    def __init__(self) -> None:
        self._seen: set[tuple[str, str, str, str, str, str]] = set()

    def observe(self, request: ModelRequest, shape: PrefixShape) -> bool:
        group = request.metadata.get("parallel_group")
        if not isinstance(group, str) or not group:
            return False
        key = (
            request.task_id,
            request.run_id or request.task_id,
            group,
            shape.provider_id,
            shape.model_id,
            shape.prefix_hash,
        )
        already_seen = key in self._seen
        self._seen.add(key)
        return already_seen


class CacheDoctor:
    """Creates a safe per-request observation; aggregate rendering lives in UsageStore."""

    @staticmethod
    def observe(
        preparation: CachePreparation, response: ModelResponse
    ) -> CacheDoctorObservation:
        cached = response.cached_input_tokens
        if cached is None:
            cached = response.cached_tokens
        reported = (
            cached is not None
            or response.cache_miss_tokens is not None
            or response.cache_write_tokens is not None
        )
        availability = CacheAvailability.REPORTED if reported else CacheAvailability.UNAVAILABLE
        miss = response.cache_miss_tokens
        if (
            miss is None
            and cached is not None
            and preparation.profile.reports_cache_miss is True
        ):
            miss = (
                max(0, response.input_tokens - cached)
                if response.input_tokens is not None
                else None
            )
        ratio = (
            cached / (cached + miss)
            if cached is not None and miss is not None and cached + miss > 0
            else (0.0 if cached == 0 and miss == 0 else None)
        )
        return CacheDoctorObservation(
            shape=preparation.shape,
            drift=preparation.drift,
            profile=preparation.profile,
            strategy=preparation.strategy,
            provider_cache_availability=availability,
            cache_hit_tokens=cached,
            cache_miss_tokens=miss,
            cache_write_tokens=response.cache_write_tokens,
            cached_input_tokens=cached,
            provider_cache_hit_ratio=ratio,
            coalesce_eligible=preparation.coalesce_eligible,
        )


class CacheIntelligence:
    """Single-request coordinator used by the existing ModelGateway."""

    def __init__(
        self,
        pipeline: CanonicalRequestPipeline | None = None,
        resolver: ProviderCapabilityResolver | None = None,
        drift_detector: PrefixDriftDetector | None = None,
        strategies: CacheStrategyRegistry | None = None,
        coalescing: ColdAnchorCoalescingAdvisor | None = None,
    ) -> None:
        self.pipeline = pipeline or CanonicalRequestPipeline()
        self.resolver = resolver or ProviderCapabilityResolver()
        self.drift_detector = drift_detector or PrefixDriftDetector()
        self.strategies = strategies or CacheStrategyRegistry()
        self.coalescing = coalescing or ColdAnchorCoalescingAdvisor()

    def prepare(self, provider: Any, request: ModelRequest) -> CachePreparation:
        identity = resolve_provider_identity(provider, request)
        effective_request = request
        if identity.selected_model and identity.selected_model != request.model:
            effective_request = request.model_copy(update={"model": identity.selected_model})
        user_config = effective_request.metadata.get("cache_capability")
        profile = self.resolver.resolve(
            identity,
            effective_request.model,
            user_config if isinstance(user_config, Mapping) else None,
        )
        shape = self.pipeline.build(effective_request, identity)
        drift = self.drift_detector.observe(shape)
        strategy = self.strategies.select(profile).apply(
            effective_request, identity, profile, shape
        )
        coalesce_eligible = self.coalescing.observe(effective_request, shape)
        metadata = dict(effective_request.metadata)
        metadata["provider_id"] = identity.provider_id
        metadata["cache_intelligence"] = {
            **shape.telemetry(),
            **drift.telemetry(),
            **profile.telemetry(),
            **strategy.telemetry(),
            "coalesce_eligible": coalesce_eligible,
        }
        if strategy.provider_payload:
            metadata["cache_provider_payload"] = strategy.provider_payload
        prepared = effective_request.model_copy(update={"metadata": metadata})
        return CachePreparation(
            provider=provider,
            request=prepared,
            identity=identity,
            shape=shape,
            drift=drift,
            profile=profile,
            strategy=strategy,
            coalesce_eligible=coalesce_eligible,
        )

    def complete(
        self, preparation: CachePreparation, response: ModelResponse
    ) -> CacheDoctorObservation:
        effective = preparation
        if response.provider_identity:
            actual_provider_id = str(
                response.provider_id
                or response.provider_identity.get("provider_id")
                or response.provider
            )
            actual_model = response.model
            identity_changed = (
                actual_provider_id != preparation.identity.provider_id
                or actual_model != preparation.request.model
            )
            if identity_changed:
                metadata = dict(preparation.request.metadata)
                metadata.pop("cache_provider_payload", None)
                metadata["provider_id"] = actual_provider_id
                request = preparation.request.model_copy(
                    update={"model": actual_model, "metadata": metadata}
                )
                identity = provider_identity_from_mapping(response.provider_identity, request)
                profile = self.resolver.resolve(identity, actual_model)
                shape = self.pipeline.build(request, identity)
                effective = replace(
                    preparation,
                    request=request,
                    identity=identity,
                    shape=shape,
                    drift=self.drift_detector.observe(shape),
                    profile=profile,
                    strategy=self.strategies.select(profile).apply(
                        request, identity, profile, shape
                    ),
                )
        profile = self.resolver.observe(
            effective.identity,
            effective.request.model,
            effective.profile,
            response,
        )
        return CacheDoctor.observe(replace(effective, profile=profile), response)


def provider_identity_from_mapping(
    raw: Mapping[str, Any], request: ModelRequest
) -> ProviderIdentity:
    provider_name = str(
        raw.get("provider_name") or request.metadata.get("provider_id") or "unknown"
    )
    provider_id = str(
        raw.get("provider_id") or request.metadata.get("provider_id") or provider_name
    )
    endpoint = raw.get("base_url") or raw.get("endpoint")
    endpoint_text = str(endpoint) if endpoint else None
    protocol = _protocol_family(raw.get("protocol_family") or raw.get("api_mode"))
    if (
        protocol is ProtocolFamily.UNKNOWN
        and provider_name.lower() in {"fake", "legacy", "fake_model"}
    ):
        protocol = ProtocolFamily.LOCAL
    adapter_capabilities = raw.get("adapter_capabilities") or ()
    return ProviderIdentity(
        provider_id=provider_id,
        provider_name=provider_name,
        endpoint=endpoint_text,
        endpoint_fingerprint=_endpoint_fingerprint(endpoint_text),
        endpoint_family=_endpoint_family(endpoint_text, protocol),
        protocol_family=protocol,
        selected_model=str(raw.get("selected_model") or request.model),
        adapter_capabilities=frozenset(str(item) for item in adapter_capabilities),
    )


def resolve_provider_identity(provider: Any, request: ModelRequest) -> ProviderIdentity:
    """Read identity facts from the adapter without treating its display name as proof."""

    raw: Mapping[str, Any] = {}
    cache_identity = getattr(provider, "cache_identity", None)
    if callable(cache_identity):
        try:
            candidate = cache_identity(request)
        except TypeError:
            candidate = cache_identity()
        if isinstance(candidate, Mapping):
            raw = candidate
    raw_identity = dict(raw)
    raw_identity.setdefault(
        "provider_id",
        request.metadata.get("provider_id")
        or raw_identity.get("provider_name")
        or getattr(provider, "provider_name", "unknown"),
    )
    raw_identity.setdefault(
        "provider_name", getattr(provider, "provider_name", "unknown")
    )
    return provider_identity_from_mapping(raw_identity, request)


def _protocol_family(value: Any) -> ProtocolFamily:
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {
        "openai_compatible",
        "openai_chat_completions",
        "chat_completions",
        "openai_chat",
    }:
        return ProtocolFamily.OPENAI_CHAT_COMPLETIONS
    if raw in {"openai_responses", "responses"}:
        return ProtocolFamily.OPENAI_RESPONSES
    if raw in {"anthropic", "anthropic_messages", "anthropic_compatible", "messages"}:
        return ProtocolFamily.ANTHROPIC_MESSAGES
    if raw in {"local", "ollama"}:
        return ProtocolFamily.LOCAL
    return ProtocolFamily.UNKNOWN


def _endpoint_family(endpoint: str | None, protocol: ProtocolFamily) -> EndpointFamily:
    if protocol is ProtocolFamily.LOCAL:
        return EndpointFamily.LOCAL
    if not endpoint:
        return EndpointFamily.UNKNOWN
    host = (urlsplit(endpoint).hostname or "").lower().rstrip(".")
    if host == "api.deepseek.com" and protocol is ProtocolFamily.OPENAI_CHAT_COMPLETIONS:
        return EndpointFamily.DEEPSEEK_OFFICIAL
    if host == "api.openai.com" and protocol in {
        ProtocolFamily.OPENAI_CHAT_COMPLETIONS,
        ProtocolFamily.OPENAI_RESPONSES,
    }:
        return EndpointFamily.OPENAI_OFFICIAL
    if host == "api.anthropic.com" and protocol is ProtocolFamily.ANTHROPIC_MESSAGES:
        return EndpointFamily.ANTHROPIC_OFFICIAL
    if host in {"localhost", "127.0.0.1", "::1"}:
        return EndpointFamily.LOCAL
    return EndpointFamily.THIRD_PARTY


def _endpoint_fingerprint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    normalized = f"{parsed.scheme.lower()}://{host}{port}{path}"
    return _sha256(normalized.encode("utf-8"))


def _volatile_findings(
    section: str, value: Any, dynamic_values: Mapping[str, str]
) -> list[VolatileFinding]:
    payload = canonical_json_bytes(value).decode("utf-8", errors="replace")
    findings: list[VolatileFinding] = []
    patterns = {
        "TIMESTAMP": (
            r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}"
            r"(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
            r"(?:Z|[+-]\d{2}:?\d{2})?)?\b"
        ),
        "UUID": (
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
        ),
        "GIT_SHA": (
            r"\b(?:git[_ -]?(?:sha|commit)|commit[_ -]?sha)"
            r"\s*[:=]?\s*[0-9a-fA-F]{7,64}\b"
        ),
        "GIT_STATUS": (
            r"\b(?:git[_ -]?status|modified[_ -]?files|current[_ -]?branch|"
            r"branch[_ -]?name)\b"
        ),
        "RANDOM_NONCE": r"\b(?:nonce|random[_ -]?(?:id|seed|value))\b",
        "DYNAMIC_CWD": (
            r"\b(?:cwd|current[_ -]?working[_ -]?directory|working[_ -]?directory)\b"
        ),
    }
    for code, pattern in patterns.items():
        if re.search(pattern, payload, flags=re.IGNORECASE):
            findings.append(VolatileFinding(code, section))
    for dynamic_name, value_id in dynamic_values.items():
        if value_id and value_id in payload:
            findings.append(VolatileFinding(dynamic_name.upper(), section))
    for key in _mapping_keys(value):
        lowered = key.lower()
        if lowered in {"timestamp", "time", "date", "created_at", "updated_at"}:
            findings.append(VolatileFinding("TIMESTAMP", section))
        elif lowered in {"request_id", "requestid"}:
            findings.append(VolatileFinding("REQUEST_ID", section))
        elif lowered in {"run_id", "runid"}:
            findings.append(VolatileFinding("RUN_ID", section))
        elif lowered in {"task_id", "taskid"}:
            findings.append(VolatileFinding("TASK_ID", section))
        elif lowered in {"nonce", "random_nonce", "random_id"}:
            findings.append(VolatileFinding("RANDOM_NONCE", section))
        elif lowered in {"cwd", "working_directory", "git_status", "git_sha", "branch"}:
            findings.append(VolatileFinding("DYNAMIC_CWD", section))
    unique: dict[tuple[str, str], VolatileFinding] = {}
    for finding in findings:
        unique[(finding.code, finding.section)] = finding
    return list(unique.values())


def _mapping_keys(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        if isinstance(value, (list, tuple)):
            return [key for item in value for key in _mapping_keys(item)]
        return []
    keys = [str(key) for key in value]
    for item in value.values():
        keys.extend(_mapping_keys(item))
    return keys


def _safe_cache_key(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value))


def _model_family(model_id: str) -> str:
    normalized = model_id.strip().lower()
    if not normalized:
        return "unknown"
    return normalized.split("/", maxsplit=1)[0].split(":", maxsplit=1)[0]


def _canonical_sort_key(value: Any) -> bytes:
    return canonical_json_bytes(value)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
