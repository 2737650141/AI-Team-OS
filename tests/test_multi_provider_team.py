from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.server as server
import app.core.events as events
from app.api.server import app
from app.core.budget import BudgetController
from app.gateway.audit import AuditLog
from app.gateway.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
    UsageEstimate,
)
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.gateway.multi_provider import (
    ModelCapabilityRegistry,
    ModelRoute,
    MultiProviderModelGateway,
    MultiProviderRoutedProvider,
    ProviderBinding,
    ProviderHealthService,
    ResolvedRuntimeRoute,
    RoleModelRouter,
    SupervisorArbitrator,
    TeamRoutingStore,
)
from app.usage.store import UsageStore


def _store(tmp_path: Path) -> TeamRoutingStore:
    return TeamRoutingStore(tmp_path / "team.sqlite")


def _gateway(tmp_path: Path, provider: object, task_id: str) -> ModelGateway:
    return ModelGateway(
        provider=provider,
        budget=BudgetController(10_000, 1.0, max_calls=10),
        audit=AuditLog(tmp_path / f"{task_id}.jsonl"),
        task_id=task_id,
    )


def _request(role: str = "executor") -> ModelRequest:
    return ModelRequest(
        request_id=f"req-{role}",
        task_id="task-mp",
        run_id="run-mp",
        agent_id=role,
        role_type=role,
        model="business-code-must-not-select-model",
        messages=[{"role": "user", "content": "reply briefly"}],
        max_output_tokens=128,
    )


def test_gt_mp01_routing_precedence_and_per_role_budget(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(
        ModelRoute(
            role="executor",
            provider_id="global-provider",
            model="global-model",
            token_budget=4000,
        )
    )
    store.set_route(
        ModelRoute(
            scope="project",
            scope_id="alpha",
            role="executor",
            provider_id="project-provider",
            model="project-model",
            token_budget=2000,
        )
    )
    router = RoleModelRouter(store)
    assert router.resolve("executor").source == "global"
    project = router.resolve("executor", project_id="alpha")
    assert (project.source, project.provider_id, project.token_budget) == (
        "project",
        "project-provider",
        2000,
    )
    task = router.resolve(
        "executor",
        project_id="alpha",
        task_route=ModelRoute(
            role="executor", provider_id="task-provider", model="task-model", token_budget=512
        ),
    )
    assert (task.source, task.provider_id, task.model, task.token_budget) == (
        "task",
        "task-provider",
        "task-model",
        512,
    )


def test_gt_mp02_missing_route_is_explicit_waiting_not_fake(tmp_path: Path) -> None:
    with pytest.raises(ProviderError) as exc:
        RoleModelRouter(_store(tmp_path)).resolve("supervisor")
    assert exc.value.code is ProviderErrorCode.CONFIG_ERROR
    assert exc.value.safe_message == "WAITING_FOR_PROVIDER_CREDENTIAL"


def test_gt_mp03_fallback_requires_complete_explicit_pair() -> None:
    with pytest.raises(ValueError, match="configured together"):
        ModelRoute(
            role="executor",
            provider_id="primary",
            model="coder",
            fallback_provider_id="secondary",
        )


class _FailingProvider:
    provider_name = "primary"

    def estimate_usage(self, _request):
        from app.gateway.contracts import UsageEstimate

        return UsageEstimate()

    def generate(self, request):
        raise ProviderError(
            ProviderErrorCode.CONNECTION_ERROR,
            "provider unavailable",
            provider="primary",
            model=request.model,
        )


def test_gt_mp04_no_silent_fallback_and_explicit_switch(tmp_path: Path) -> None:
    events._store = None
    events.init(tmp_path / "events")
    store = _store(tmp_path)
    store.set_route(ModelRoute(role="executor", provider_id="primary", model="coder"))
    router = RoleModelRouter(store)
    gateway = MultiProviderModelGateway(
        router,
        {"primary": ProviderBinding("primary", _gateway(tmp_path, _FailingProvider(), "p"))},
        store,
    )
    with pytest.raises(ProviderError):
        gateway.generate(_request())

    store.set_route(
        ModelRoute(
            role="executor",
            provider_id="primary",
            model="coder",
            fallback_provider_id="secondary",
            fallback_model="backup-coder",
        )
    )
    switches: list[tuple[str, str]] = []
    gateway = MultiProviderModelGateway(
        router,
        {
            "primary": ProviderBinding("primary", _gateway(tmp_path, _FailingProvider(), "p2")),
            "secondary": ProviderBinding(
                "secondary", _gateway(tmp_path, DeterministicFakeModel(), "s")
            ),
        },
        store,
        on_switch=lambda before, after: switches.append((before.provider_id, after.provider_id)),
    )
    response, decision, switched = gateway.generate(_request())
    assert switched is True
    assert decision.provider_id == "secondary"
    assert response.model == "backup-coder"
    assert switches == [("primary", "secondary")]
    profiles = store.performance()
    assert sum(profile.provider_errors for profile in profiles) == 2
    assert sum(profile.successes for profile in profiles) == 1


def test_gt_mp06_supervisor_arbitration_is_deterministic() -> None:
    chosen = SupervisorArbitrator.choose(
        [
            {"source": "executor_confidence", "value": "pass"},
            {"source": "reviewer", "value": "reject"},
            {"source": "tests", "value": "failed"},
        ]
    )
    assert chosen["value"] == "failed"


def _reset_server(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    server._resolver = None


def test_gt_mp07_team_routing_api_and_test_provider_never_claim_real_ready(
    tmp_path: Path, monkeypatch
) -> None:
    _reset_server(tmp_path, monkeypatch)
    with TestClient(app) as client:
        provider = client.post(
            "/settings/connections/providers",
            json={
                "provider_name": "M6 isolated",
                "base_url": "https://third-party-test.invalid/v1",
                "default_model": "m4-test-small",
                "test_provider": True,
            },
        ).json()
        provider_id = provider["provider_id"]
        client.put(
            f"/settings/connections/providers/{provider_id}/credential",
            json={"api_key": "TEST-TOKEN-M6-ISOLATED", "storage_mode": "session"},
        )
        for role in ("supervisor", "executor", "reviewer"):
            saved = client.put(
                f"/settings/ai-team/routing/{role}",
                json={"provider_id": provider_id, "model": "m4-test-small"},
            )
            assert saved.status_code == 200
        routing = client.get("/settings/ai-team/routing").json()
        executor = next(item for item in routing["roles"] if item["role"] == "executor")
        reviewer = next(item for item in routing["roles"] if item["role"] == "reviewer")
        assert executor["source"] == "global"
        assert reviewer["warning"] == "EXECUTOR_REVIEWER_NOT_INDEPENDENT"
        assert routing["fallback_policy"] == "NO_SILENT_FALLBACK"
        result = client.post("/settings/ai-team/test").json()
        statuses = {item["role"]: item["status"] for item in result["results"]}
        assert statuses["supervisor"] == "ISOLATED_TEST_ONLY"
        assert statuses["executor"] == "ISOLATED_TEST_ONLY"
        assert statuses["reviewer"] == "ISOLATED_TEST_ONLY"
        assert statuses["planner"] == "WAITING_FOR_PROVIDER_CREDENTIAL"
        assert result["ready"] == 0
        assert result["status"] == "PARTIAL"
        serialized = str(routing) + str(result)
        assert "TEST-TOKEN-M6-ISOLATED" not in serialized


def test_gt_mp08_project_route_api_overrides_global(tmp_path: Path, monkeypatch) -> None:
    _reset_server(tmp_path, monkeypatch)
    with TestClient(app) as client:
        providers = []
        for index in (1, 2):
            providers.append(
                client.post(
                    "/settings/connections/providers",
                    json={
                        "provider_name": f"M6 provider {index}",
                        "base_url": "https://third-party-test.invalid/v1",
                        "test_provider": True,
                    },
                ).json()["provider_id"]
            )
        client.put(
            "/settings/ai-team/routing/planner",
            json={"provider_id": providers[0], "model": "global-planner"},
        )
        client.put(
            "/settings/ai-team/routing/planner",
            json={
                "provider_id": providers[1],
                "model": "project-planner",
                "scope": "project",
                "project_id": "alpha",
            },
        )
        card = next(
            item
            for item in client.get(
                "/settings/ai-team/routing", params={"project_id": "alpha"}
            ).json()["roles"]
            if item["role"] == "planner"
        )
        assert card["model"] == "project-planner"
        assert card["source"] == "project"


def test_gt_mp05_explicit_fallback_is_reported_in_route_card(tmp_path: Path, monkeypatch) -> None:
    _reset_server(tmp_path, monkeypatch)
    with TestClient(app) as client:
        provider_ids = [
            client.post(
                "/settings/connections/providers",
                json={
                    "provider_name": f"Fallback provider {index}",
                    "base_url": "https://third-party-test.invalid/v1",
                    "test_provider": True,
                },
            ).json()["provider_id"]
            for index in (1, 2)
        ]
        response = client.put(
            "/settings/ai-team/routing/executor",
            json={
                "provider_id": provider_ids[0],
                "model": "primary-model",
                "fallback_provider_id": provider_ids[1],
                "fallback_model": "explicit-backup",
            },
        )
        assert response.status_code == 200
        assert response.json()["card"]["fallback"] == {
            "provider_id": provider_ids[1],
            "model": "explicit-backup",
        }


def test_gt_mp09_unknown_capability_is_never_fabricated() -> None:
    capability = ModelCapabilityRegistry().get("provider", "unverified-model")
    assert capability.text is True
    assert capability.tool_calling is None
    assert capability.vision is None


def test_gt_mp10_provider_health_has_explicit_states() -> None:
    assert (
        ProviderHealthService.status(configured=False, health="missing")
        == "WAITING_FOR_PROVIDER_CREDENTIAL"
    )
    assert (
        ProviderHealthService.status(configured=True, health="healthy", invocation_status="success")
        == "REAL_READY"
    )


class _RawProvider:
    provider_name = "raw-provider"

    def estimate_usage(self, request: ModelRequest) -> UsageEstimate:
        return UsageEstimate(
            estimated_input_tokens=1,
            estimated_max_output_tokens=4,
            estimated_max_cost=0.0005,
        )

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model=request.model,
            structured_output={"ok": True},
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
            estimated_cost=0.001,
            latency_ms=11,
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="healthy", provider=self.provider_name, model="routed")


class _CapturingProvider(_RawProvider):
    provider_name = "capturing-provider"

    def __init__(self) -> None:
        self.seen_models: list[str] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.seen_models.append(request.model)
        return super().generate(request)


def test_gt_mp11_runtime_provider_routes_by_request_role(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(ModelRoute(role="planner", provider_id="p1", model="planner-specialist"))
    provider = MultiProviderRoutedProvider(
        RoleModelRouter(store), {"p1": _RawProvider()}, store, project_id="alpha"
    )
    response = provider.generate(_request("planner"))
    assert response.model == "planner-specialist"
    assert provider.call_count == 1


def test_r1a_runtime_route_resolution_is_immutable_and_role_based(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(ModelRoute(role="planner", provider_id="p1", model="planner-specialist"))
    route = RoleModelRouter(store).resolve_route("planner")
    assert (route.provider_id, route.model_id, route.source) == (
        "p1",
        "planner-specialist",
        "global",
    )
    with pytest.raises(Exception):
        route.model_id = "mutated"  # type: ignore[misc]


def test_r1a_executor_consumes_resolved_route_without_reselection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(ModelRoute(role="planner", provider_id="p2", model="downstream-default"))
    selected = _CapturingProvider()
    conflicting = _CapturingProvider()
    route = ResolvedRuntimeRoute(
        provider_id="p1",
        model_id="semantic-model",
        source="global",
        role="planner",
    )
    provider = MultiProviderRoutedProvider(
        RoleModelRouter(store), {"p1": selected, "p2": conflicting}, store, route=route
    )
    response = provider.generate(_request("planner"))
    assert response.provider_id == "p1"
    assert selected.seen_models == ["semantic-model"]
    assert conflicting.seen_models == []


def test_r1a_unknown_provider_fails_loud_without_fallback(tmp_path: Path) -> None:
    store = _store(tmp_path)
    route = ResolvedRuntimeRoute(
        provider_id="missing-provider",
        model_id="missing-model",
        source="global",
        role="planner",
    )
    provider = MultiProviderRoutedProvider(RoleModelRouter(store), {}, store, route=route)
    with pytest.raises(ProviderError) as exc:
        provider.generate(_request("planner"))
    assert exc.value.code is ProviderErrorCode.CONFIG_ERROR
    assert provider.call_count == 0


def test_gt_mp12_performance_profile_is_observational_only(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(ModelRoute(role="reviewer", provider_id="p1", model="review-model"))
    provider = MultiProviderRoutedProvider(RoleModelRouter(store), {"p1": _RawProvider()}, store)
    provider.generate(_request("reviewer"))
    profile = store.performance()[0]
    assert profile.calls == 1
    assert profile.success_rate == 1.0
    assert profile.latency_ms_avg == 11
    assert profile.cost == 0.001
    assert RoleModelRouter(store).resolve("reviewer").model == "review-model"


def test_outer_gateway_attributes_explicit_fallback_to_effective_provider(
    tmp_path: Path,
) -> None:
    class Secondary(_RawProvider):
        provider_name = "secondary-adapter"

        def cache_identity(self, _request: ModelRequest) -> dict[str, object]:
            return {
                "provider_name": self.provider_name,
                "endpoint": "https://secondary.example/v1/chat/completions",
                "api_mode": "openai_compatible",
            }

        def generate(self, request: ModelRequest) -> ModelResponse:
            response = super().generate(request)
            response.cached_input_tokens = 2
            response.cache_miss_tokens = 1
            response.usage_source = "REPORTED"
            return response

    store = _store(tmp_path)
    store.set_route(
        ModelRoute(
            role="executor",
            provider_id="primary",
            model="primary-model",
            fallback_provider_id="secondary",
            fallback_model="secondary-model",
        )
    )
    routed = MultiProviderRoutedProvider(
        RoleModelRouter(store),
        {"primary": _FailingProvider(), "secondary": Secondary()},
        store,
    )
    usage = UsageStore(tmp_path)
    gateway = ModelGateway(
        routed,
        BudgetController(10_000, 1.0, max_calls=4),
        AuditLog(tmp_path / "fallback-audit.jsonl"),
        "task-mp",
        "run-mp",
        usage_store=usage,
    )
    response = gateway.generate(_request(), max_retries=0)
    assert response.provider_id == "secondary"
    assert response.model == "secondary-model"
    assert response.cache_diagnostics is not None
    assert response.cache_diagnostics["provider_id"] == "secondary"
    assert response.cache_diagnostics["model_id"] == "secondary-model"
    with usage._connect() as conn:  # noqa: SLF001
        row = conn.execute(
            "SELECT provider_id, model_id FROM model_usage WHERE call_id='req-executor'"
        ).fetchone()
    assert tuple(row) == ("secondary", "secondary-model")


def test_role_cost_budget_fails_before_provider_call(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.set_route(
        ModelRoute(
            role="planner",
            provider_id="p1",
            model="planner-model",
            cost_budget=0.0001,
        )
    )
    provider = MultiProviderRoutedProvider(RoleModelRouter(store), {"p1": _RawProvider()}, store)
    with pytest.raises(ProviderError) as exc:
        provider.generate(_request("planner"))
    assert exc.value.code is ProviderErrorCode.BUDGET_INSUFFICIENT
    assert provider.call_count == 0
