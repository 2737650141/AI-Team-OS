from __future__ import annotations

import json
from pathlib import Path

from app.core.budget import BudgetController
from app.gateway.audit import AuditLog
from app.gateway.cache_intelligence import (
    CacheIntelligence,
    CacheStrategyRegistry,
    CapabilitySource,
    DriftReason,
    DriftStatus,
    PrefixDriftDetector,
    ProtocolFamily,
    ProviderCapabilityResolver,
    ProviderIdentity,
    canonical_json_bytes,
    canonical_schema_fingerprint,
    canonicalize_tools,
    environment_delta,
    safe_cache_telemetry,
)
from app.gateway.contracts import ModelRequest, ModelResponse
from app.gateway.model_gateway import ModelGateway
from app.gateway.tool_gateway import ToolGateway
from app.usage.reconciler import UsageReconciler
from app.usage.store import UsageStore, _summarize


def _identity(
    *,
    provider_id: str = "provider",
    endpoint: str | None = "https://gateway.example/v1",
    protocol: ProtocolFamily = ProtocolFamily.OPENAI_CHAT_COMPLETIONS,
    name: str = "gateway",
) -> ProviderIdentity:
    from app.gateway.cache_intelligence import _endpoint_family, _endpoint_fingerprint

    return ProviderIdentity(
        provider_id=provider_id,
        provider_name=name,
        endpoint=endpoint,
        endpoint_fingerprint=_endpoint_fingerprint(endpoint),
        endpoint_family=_endpoint_family(endpoint, protocol),
        protocol_family=protocol,
    )


def _request(
    *,
    model: str = "gpt-5.6-sol",
    system: str = "stable contract",
    metadata: dict | None = None,
) -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        task_id="task-1",
        run_id="run-1",
        agent_id="planner",
        role_type="planner",
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": "dynamic turn"},
        ],
        metadata=metadata or {},
    )


def test_cache_mp01_mp02_tool_order_and_recursive_object_keys() -> None:
    tools_a = [
        {"name": "z", "schema": {"properties": {"b": 1, "a": 2}}},
        {"name": "a", "schema": {"type": "object"}},
    ]
    tools_b = [
        {"name": "a", "schema": {"type": "object"}},
        {"name": "z", "schema": {"properties": {"a": 2, "b": 1}}},
    ]
    assert canonicalize_tools(tools_a) == canonicalize_tools(tools_b)
    assert canonical_json_bytes({"b": {"d": 2, "c": 1}, "a": 0}) == canonical_json_bytes(
        {"a": 0, "b": {"c": 1, "d": 2}}
    )


def test_cache_mp_tool_gateway_manifest_changes_prefix_tools_hash(tmp_path: Path) -> None:
    from app.tools.spec import RiskLevel, ToolSpec

    def handler(value: str) -> dict:
        return {"value": value}

    hashes: list[str] = []
    provider = type("Provider", (), {"provider_name": "fake"})()
    for schema in ({"value": "str"}, {"value": "int"}):
        gateway = ToolGateway(AuditLog(tmp_path / f"{schema['value']}.jsonl"), "task-1")
        gateway.register(
            ToolSpec(
                name="read",
                description="read value",
                input_schema=schema,
                risk_level=RiskLevel.SAFE,
                read_only=True,
                handler=handler,
            )
        )
        request = _request(metadata={"cache_tools": gateway.cache_tool_manifest()})
        hashes.append(CacheIntelligence().prepare(provider, request).shape.tools_hash)
    assert hashes[0] != hashes[1]


def test_cache_mp03_mp04_arrays_preserved_and_schema_fingerprint_stable() -> None:
    schema_a = {"oneOf": [{"type": "string"}, {"type": "number"}], "properties": {"b": 1, "a": 2}}
    schema_b = {"properties": {"a": 2, "b": 1}, "oneOf": [{"type": "string"}, {"type": "number"}]}
    schema_reordered = {
        "oneOf": [{"type": "number"}, {"type": "string"}],
        "properties": {"a": 2, "b": 1},
    }
    assert canonical_schema_fingerprint(schema_a) == canonical_schema_fingerprint(schema_b)
    assert canonical_schema_fingerprint(schema_a) != canonical_schema_fingerprint(schema_reordered)


def test_cache_mp05_mp07_prefix_shape_ignores_runtime_ids_and_is_stable() -> None:
    provider = type("Provider", (), {"provider_name": "fake"})()
    intelligence = CacheIntelligence()
    first = intelligence.prepare(provider, _request(metadata={"request_nonce": "x"}))
    second = intelligence.prepare(
        provider,
        _request(metadata={"request_nonce": "y"}).model_copy(update={"request_id": "request-2"}),
    )
    assert first.shape.prefix_hash == second.shape.prefix_hash
    assert first.shape.timestamp != ""
    assert not any(
        item.code in {"REQUEST_ID", "RUN_ID", "TASK_ID"}
        for item in first.shape.volatile_findings
    )


def test_cache_mp06_volatile_timestamp_is_reported_not_removed() -> None:
    provider = type("Provider", (), {"provider_name": "fake"})()
    prepared = CacheIntelligence().prepare(
        provider,
        _request(system="stable contract generated 2026-08-15T12:30:00Z"),
    )
    assert any(item.code == "TIMESTAMP" for item in prepared.shape.volatile_findings)
    assert prepared.request.messages[0]["content"].endswith("Z")


def test_cache_mp08_mp09_drift_locates_system_and_tool_schema_changes() -> None:
    detector = PrefixDriftDetector()
    provider = type("Provider", (), {"provider_name": "fake"})()
    intelligence = CacheIntelligence(drift_detector=detector)
    first = intelligence.prepare(provider, _request())
    assert first.drift.status is DriftStatus.UNKNOWN
    changed_system = intelligence.prepare(provider, _request(system="changed contract"))
    assert DriftReason.SYSTEM_CHANGED in changed_system.drift.reasons
    tool_a = _request(metadata={"cache_tools": [{"name": "read", "schema": {"type": "string"}}]})
    tool_b = _request(metadata={"cache_tools": [{"name": "read", "schema": {"type": "number"}}]})
    intelligence.prepare(provider, tool_a)
    changed_tools = intelligence.prepare(provider, tool_b)
    assert DriftReason.TOOL_SCHEMA_CHANGED in changed_tools.drift.reasons
    assert changed_tools.drift.first_changed_section == "tools"


def test_cache_mp10_mp12_unknown_and_compatible_model_names_stay_passive() -> None:
    resolver = ProviderCapabilityResolver()
    third_party = _identity()
    gpt = resolver.resolve(third_party, "gpt-5.6-sol")
    claude = resolver.resolve(third_party, "claude-sonnet")
    assert gpt.source is CapabilitySource.UNKNOWN
    assert claude.source is CapabilitySource.UNKNOWN
    assert gpt.prompt_cache_mode.value == "passive"
    assert CacheStrategyRegistry().select(gpt).name == "passive"


def test_cache_mp13_mp15_exact_official_endpoint_profiles_select_strategies() -> None:
    resolver = ProviderCapabilityResolver()
    deepseek = resolver.resolve(
        _identity(
            provider_id="DeepSeek Official",
            endpoint="https://api.deepseek.com",
            name="DeepSeek Official",
        ),
        "deepseek-v4-flash",
    )
    openai = resolver.resolve(
        _identity(
            provider_id="OpenAI Official",
            endpoint="https://api.openai.com/v1",
            name="OpenAI",
        ),
        "gpt-5.6-sol",
    )
    anthropic = resolver.resolve(
        _identity(
            provider_id="Anthropic Official",
            endpoint="https://api.anthropic.com",
            protocol=ProtocolFamily.ANTHROPIC_MESSAGES,
            name="Anthropic",
        ),
        "claude-sonnet",
    )
    registry = CacheStrategyRegistry()
    assert registry.select(deepseek).name == "deepseek"
    assert registry.select(openai).name == "openai"
    assert registry.select(anthropic).name == "anthropic"


def test_cache_mp11_user_configuration_overrides_unknown_without_model_inference() -> None:
    resolver = ProviderCapabilityResolver()
    profile = resolver.resolve(
        _identity(),
        "claude-sonnet",
        {"supports_cache_control": True, "prompt_cache_mode": "cache_control"},
    )
    assert profile.source is CapabilitySource.USER_CONFIGURED
    assert profile.supports_cache_control is True


def test_cache_mp14_mp16_usage_normalization_preserves_reported_categories() -> None:
    normalized = UsageReconciler.anthropic_usage(
        {
            "input_tokens": 10,
            "cache_read_input_tokens": 30,
            "cache_creation_input_tokens": 5,
            "output_tokens": 4,
        }
    )
    assert normalized["input_tokens"] == 45
    assert normalized["cached_input_tokens"] == 30
    assert normalized["cache_write_tokens"] == 5
    assert UsageReconciler.openai_usage({"prompt_tokens": 100, "completion_tokens": 2})[
        "cached_input_tokens"
    ] is None


def test_cache_mp17_mp18_unreported_is_unavailable_and_app_side_is_separate() -> None:
    row = {
        "input_tokens": 100,
        "cached_input_tokens": None,
        "total_tokens": 100,
        "output_tokens": 0,
        "latency_ms": 1,
        "timestamp": "2026-08-15T00:00:00+00:00",
        "usage_source": "REPORTED",
        "cost_total": 0.0,
        "currency": "USD",
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "other_tokens": None,
        "compression_triggered": 0,
        "compression_tokens_before": None,
        "compression_tokens_after": None,
        "scope": "user_task",
        "task_id": "task-1",
        "run_id": "run-1",
        "call_id": "call-1",
        "role": "planner",
        "agent_id": "planner",
        "provider_id": "gateway",
        "provider_name": "gateway",
        "model_id": "gpt-5.6-sol",
        "estimated_input_tokens": None,
        "estimated_output_tokens": None,
        "context_tokens_before": None,
        "context_tokens_after": None,
        "context_limit": None,
        "cache_diagnostics": {
            "status": "STABLE",
            "estimated_prefix_tokens": 50,
            "provider_cache_availability": "UNAVAILABLE",
            "source": "UNKNOWN",
            "confidence": "UNKNOWN",
            "strategy": "passive",
        },
    }
    first = dict(row)
    first["cache_diagnostics"] = {
        **row["cache_diagnostics"],
        "status": "UNKNOWN",
    }
    second = dict(row)
    second.update(
        call_id="call-2",
        timestamp="2026-08-15T00:00:01+00:00",
        cache_diagnostics={**row["cache_diagnostics"], "status": "STABLE"},
    )
    summary = _summarize([first, second])
    assert summary["cache_hit_tokens"] is None
    assert summary["cache_doctor"]["provider_cache"]["status"] == "Unavailable"
    assert summary["cache_doctor"]["provider_cache"]["hit_ratio"] is None
    assert summary["cache_doctor"]["application_prefix"]["status"] == "AVAILABLE"
    assert summary["cache_doctor"]["application_prefix"]["stability"] == 1


def test_cache_mp19_diagnostic_observation_does_not_pollute_user_task(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    from tests.test_usage_attribution import _usage

    store.record(_usage("user", scope="user_task"))
    store.record(_usage("diag", scope="diagnostic"))
    store.record_cache_observation("diag", "diagnostic", "task-1", "run-1", {"status": "STABLE"})
    summary = store.summary(run_id="run-1", days=None, scope="user_task")
    assert summary["requests"] == 1
    assert summary["cache_doctor"]["application_prefix"]["status"] == "Unavailable"


def test_cache_mp20_task_run_attribution_remains_unchanged(tmp_path: Path) -> None:
    store = UsageStore(tmp_path)
    from tests.test_usage_attribution import _usage

    store.record(_usage("call", task_id="parent", run_id="run-parent"))
    store.record_cache_observation(
        "call",
        "user_task",
        "parent",
        "run-parent",
        {"status": "STABLE", "estimated_prefix_tokens": 10},
    )
    assert store.summary(run_id="run-parent", days=None, scope="user_task")["requests"] == 1
    assert store.summary(run_id="other", days=None, scope="user_task")["requests"] == 0


def test_cache_mp_environment_delta_is_detector_only() -> None:
    delta = environment_delta(
        {"branch": "main", "files": []},
        {"branch": "feature", "files": ["a.py"]},
    )
    assert delta.changed_keys == ("branch", "files")
    assert delta.relocation_safe is False


def test_cache_mp_provider_response_diagnostics_are_privacy_minimal(tmp_path: Path) -> None:
    class Provider:
        provider_name = "fake"

        def estimate_usage(self, request):
            from app.gateway.contracts import UsageEstimate

            return UsageEstimate(estimated_input_tokens=10, estimated_max_output_tokens=10)

        def generate(self, request):
            return ModelResponse(
                request_id=request.request_id,
                provider="fake",
                model=request.model,
                raw_text='{"ok":true}',
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                usage_source="REPORTED",
            )

    store = UsageStore(tmp_path)
    gateway = ModelGateway(
        Provider(),
        BudgetController(1000, 1.0),
        AuditLog(tmp_path / "audit.jsonl"),
        "task-1",
        "run-1",
        usage_store=store,
    )
    response = gateway.generate(_request(model="local-model"))
    assert response.cache_diagnostics is not None
    payload = json.dumps(response.cache_diagnostics)
    assert "dynamic turn" not in payload
    assert "Authorization" not in payload
    with Path(store.path).open("rb") as handle:
        raw = handle.read()
    assert b"dynamic turn" not in raw


def test_cache_mp_reported_hit_completes_without_dropping_diagnostics() -> None:
    provider = type("Provider", (), {"provider_name": "fake"})()
    intelligence = CacheIntelligence()
    preparation = intelligence.prepare(provider, _request(model="local-model"))
    observation = intelligence.complete(
        preparation,
        ModelResponse(
            request_id="request-1",
            provider="fake",
            model="local-model",
            input_tokens=100,
            output_tokens=5,
            cached_input_tokens=80,
            cache_miss_tokens=20,
            usage_source="REPORTED",
        ),
    )
    assert observation.provider_cache_availability.value == "REPORTED"
    assert observation.provider_cache_hit_ratio == 0.8


def test_cache_mp_provider_reported_miss_overrides_input_minus_cached() -> None:
    row = {
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "cache_miss_tokens": 5,
        "total_tokens": 101,
        "output_tokens": 1,
        "latency_ms": 1,
        "timestamp": "2026-08-15T00:00:00+00:00",
        "usage_source": "REPORTED",
        "cost_total": None,
        "currency": None,
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "other_tokens": None,
        "compression_triggered": 0,
        "compression_tokens_before": None,
        "compression_tokens_after": None,
        "context_tokens_after": None,
        "scope": "user_task",
        "task_id": "task-1",
        "run_id": "run-1",
        "call_id": "call-1",
        "role": "planner",
        "agent_id": "planner",
        "provider_id": "provider",
        "provider_name": "provider",
        "model_id": "model",
    }
    summary = _summarize([row])
    assert summary["cache_miss_tokens"] == 5
    assert summary["token_cache_hit_ratio"] == 0.8


def test_cache_mp_interleaved_system_message_changes_prefix_shape() -> None:
    provider = type("Provider", (), {"provider_name": "fake"})()
    intelligence = CacheIntelligence()
    first = _request().model_copy(
        update={
            "messages": [
                {"role": "system", "content": "A"},
                {"role": "user", "content": "U"},
                {"role": "system", "content": "B"},
            ]
        }
    )
    second = first.model_copy(
        update={
            "messages": [
                {"role": "system", "content": "A"},
                {"role": "system", "content": "B"},
                {"role": "user", "content": "U"},
            ]
        }
    )
    assert intelligence.prepare(provider, first).shape.prefix_hash != intelligence.prepare(
        provider, second
    ).shape.prefix_hash


def test_cache_mp_safe_telemetry_drops_unknown_and_nested_fields() -> None:
    safe = safe_cache_telemetry(
        {
            "prefix_hash": "abc",
            "raw_prompt": "secret prompt",
            "provider_id": {"nested": "forbidden"},
            "reasons": ["SYSTEM_CHANGED"],
        }
    )
    assert safe == {"prefix_hash": "abc", "reasons": ["SYSTEM_CHANGED"]}
