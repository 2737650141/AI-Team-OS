"""Governed multi-provider routing for M6-A.

Provider SDK and OpenAI-compatible types terminate at the adapter boundary.  Business code routes
by stable role slots and receives the existing ModelResponse contract.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.gateway.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorCode,
    ProviderHealth,
)
from app.gateway.model_gateway import ModelGateway
from app.memory.models import utc_now

ROLE_MODEL_SLOTS = (
    "supervisor",
    "planner",
    "researcher",
    "executor",
    "reviewer",
    "vision",
    "fast",
    "deep_reasoning",
    "voice_reasoning",
)


@dataclass(frozen=True)
class ResolvedRuntimeRoute:
    """Immutable semantic provider/model decision consumed by executors."""

    provider_id: str
    model_id: str
    source: str
    role: str = ""
    token_budget: int = 4096
    cost_budget: float | None = None
    fallback_provider_id: str | None = None
    fallback_model_id: str | None = None


class ModelRoute(BaseModel):
    scope: Literal["global", "project"] = "global"
    scope_id: str = "global"
    role: str
    provider_id: str
    model: str
    fallback_provider_id: str | None = None
    fallback_model: str | None = None
    token_budget: int = Field(default=4096, gt=0)
    cost_budget: float | None = Field(default=None, ge=0)
    updated_at: str = Field(default_factory=utc_now)

    def model_post_init(self, __context: Any) -> None:
        if self.role not in ROLE_MODEL_SLOTS:
            raise ValueError(f"unknown role model slot: {self.role}")
        if bool(self.fallback_provider_id) != bool(self.fallback_model):
            raise ValueError("fallback provider and model must be configured together")


class RouteDecision(BaseModel):
    role: str
    provider_id: str
    model: str
    source: str
    fallback_provider_id: str | None = None
    fallback_model: str | None = None
    token_budget: int = 4096
    cost_budget: float | None = None


class ModelCapability(BaseModel):
    provider_id: str
    model: str
    text: bool = True
    structured_output: bool | None = None
    tool_calling: bool | None = None
    vision: bool | None = None
    streaming: bool | None = None


class ModelPerformanceProfile(BaseModel):
    provider_id: str
    model: str
    role: str
    calls: int = 0
    successes: int = 0
    structured_output_successes: int = 0
    coding_successes: int = 0
    review_catches: int = 0
    tool_call_successes: int = 0
    provider_errors: int = 0
    latency_ms_avg: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    updated_at: str | None = None

    @property
    def success_rate(self) -> float | None:
        return round(self.successes / self.calls, 4) if self.calls else None


class TeamRoutingStore:
    """SQLite route and telemetry store. It never stores provider credentials or prompts."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS role_model_routes (
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    fallback_provider_id TEXT,
                    fallback_model TEXT,
                    token_budget INTEGER NOT NULL,
                    cost_budget REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope, scope_id, role)
                );
                CREATE TABLE IF NOT EXISTS model_performance (
                    provider_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    role TEXT NOT NULL,
                    calls INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    structured_output_successes INTEGER NOT NULL DEFAULT 0,
                    coding_successes INTEGER NOT NULL DEFAULT 0,
                    review_catches INTEGER NOT NULL DEFAULT 0,
                    tool_call_successes INTEGER NOT NULL DEFAULT 0,
                    provider_errors INTEGER NOT NULL DEFAULT 0,
                    latency_ms_total INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    cost_total REAL,
                    cost_available INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(provider_id, model, role)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def set_route(self, route: ModelRoute) -> ModelRoute:
        route = route.model_copy(update={"updated_at": utc_now()})
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO role_model_routes
                (scope, scope_id, role, provider_id, model, fallback_provider_id,
                 fallback_model, token_budget, cost_budget, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, scope_id, role) DO UPDATE SET
                  provider_id=excluded.provider_id, model=excluded.model,
                  fallback_provider_id=excluded.fallback_provider_id,
                  fallback_model=excluded.fallback_model,
                  token_budget=excluded.token_budget, cost_budget=excluded.cost_budget,
                  updated_at=excluded.updated_at""",
                (
                    route.scope,
                    route.scope_id,
                    route.role,
                    route.provider_id,
                    route.model,
                    route.fallback_provider_id,
                    route.fallback_model,
                    route.token_budget,
                    route.cost_budget,
                    route.updated_at,
                ),
            )
            conn.commit()
        return route

    def get_route(self, scope: str, scope_id: str, role: str) -> ModelRoute | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM role_model_routes WHERE scope=? AND scope_id=? AND role=?",
                (scope, scope_id, role),
            ).fetchone()
        return ModelRoute(**dict(row)) if row else None

    def list_routes(
        self, scope: str | None = None, scope_id: str | None = None
    ) -> list[ModelRoute]:
        query = "SELECT * FROM role_model_routes"
        values: list[str] = []
        filters: list[str] = []
        if scope:
            filters.append("scope=?")
            values.append(scope)
        if scope_id:
            filters.append("scope_id=?")
            values.append(scope_id)
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY scope, scope_id, role"
        with self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        return [ModelRoute(**dict(row)) for row in rows]

    def delete_route(self, scope: str, scope_id: str, role: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM role_model_routes WHERE scope=? AND scope_id=? AND role=?",
                (scope, scope_id, role),
            )
            conn.commit()
        return bool(cursor.rowcount)

    def record_call(
        self,
        decision: RouteDecision,
        response: ModelResponse | None,
        *,
        success: bool,
        structured_output_success: bool = False,
        coding_success: bool = False,
        review_catch: bool = False,
        tool_call_success: bool = False,
    ) -> None:
        latency = response.latency_ms if response else 0
        input_tokens = response.input_tokens if response else 0
        output_tokens = response.output_tokens if response else 0
        cost = response.estimated_cost if response else None
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO model_performance
                (provider_id, model, role, calls, successes, structured_output_successes,
                 coding_successes, review_catches, tool_call_successes, provider_errors,
                 latency_ms_total, input_tokens, output_tokens, cost_total, cost_available,
                 updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, model, role) DO UPDATE SET
                  calls=calls+1,
                  successes=successes+excluded.successes,
                  structured_output_successes=structured_output_successes+excluded.structured_output_successes,
                  coding_successes=coding_successes+excluded.coding_successes,
                  review_catches=review_catches+excluded.review_catches,
                  tool_call_successes=tool_call_successes+excluded.tool_call_successes,
                  provider_errors=provider_errors+excluded.provider_errors,
                  latency_ms_total=latency_ms_total+excluded.latency_ms_total,
                  input_tokens=input_tokens+excluded.input_tokens,
                  output_tokens=output_tokens+excluded.output_tokens,
                  cost_total=CASE WHEN cost_available=0 OR excluded.cost_available=0
                    THEN NULL ELSE COALESCE(cost_total, 0)+COALESCE(excluded.cost_total, 0) END,
                  cost_available=CASE
                    WHEN cost_available=0 OR excluded.cost_available=0 THEN 0 ELSE 1 END,
                  updated_at=excluded.updated_at""",
                (
                    decision.provider_id,
                    decision.model,
                    decision.role,
                    int(success),
                    int(structured_output_success),
                    int(coding_success),
                    int(review_catch),
                    int(tool_call_success),
                    int(not success),
                    latency,
                    input_tokens,
                    output_tokens,
                    cost,
                    int(cost is not None),
                    utc_now(),
                ),
            )
            conn.commit()

    def performance(self) -> list[ModelPerformanceProfile]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_performance ORDER BY role, provider_id, model"
            ).fetchall()
        profiles: list[ModelPerformanceProfile] = []
        for row in rows:
            data = dict(row)
            calls = data.pop("calls")
            latency_total = data.pop("latency_ms_total")
            cost_available = bool(data.pop("cost_available"))
            cost_total = data.pop("cost_total")
            profiles.append(
                ModelPerformanceProfile(
                    calls=calls,
                    latency_ms_avg=round(latency_total / calls, 2) if calls else None,
                    cost=cost_total if cost_available else None,
                    **data,
                )
            )
        return profiles


class RoleModelRouter:
    """Frozen precedence: task explicit > project role > global role > configured fallback."""

    def __init__(self, store: TeamRoutingStore) -> None:
        self.store = store

    def resolve(
        self,
        role: str,
        *,
        project_id: str | None = None,
        task_route: ModelRoute | None = None,
    ) -> RouteDecision:
        if role not in ROLE_MODEL_SLOTS:
            raise ValueError(f"unknown role model slot: {role}")
        route = task_route
        source: Literal["task", "project", "global"] = "task"
        if route is not None and route.role != role:
            raise ValueError("task route role mismatch")
        if route is None and project_id:
            route = self.store.get_route("project", project_id, role)
            source = "project"
        if route is None:
            route = self.store.get_route("global", "global", role)
            source = "global"
        if route is None:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "WAITING_FOR_PROVIDER_CREDENTIAL",
                model="",
            )
        return RouteDecision(
            role=role,
            provider_id=route.provider_id,
            model=route.model,
            source=source,
            fallback_provider_id=route.fallback_provider_id,
            fallback_model=route.fallback_model,
            token_budget=route.token_budget,
            cost_budget=route.cost_budget,
        )

    def resolve_route(
        self,
        role: str,
        *,
        project_id: str | None = None,
        task_route: ModelRoute | None = None,
    ) -> ResolvedRuntimeRoute:
        route = self.resolve(role, project_id=project_id, task_route=task_route)
        return ResolvedRuntimeRoute(
            provider_id=route.provider_id,
            model_id=route.model,
            source=route.source,
            role=route.role,
            token_budget=route.token_budget,
            cost_budget=route.cost_budget,
            fallback_provider_id=route.fallback_provider_id,
            fallback_model_id=route.fallback_model,
        )


class ModelCapabilityRegistry:
    """Conservative capability facts. Unknown fields remain None instead of being fabricated."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ModelCapability] = {}

    def register(self, capability: ModelCapability) -> None:
        self._items[(capability.provider_id, capability.model)] = capability

    def get(self, provider_id: str, model: str) -> ModelCapability:
        return self._items.get(
            (provider_id, model), ModelCapability(provider_id=provider_id, model=model)
        )


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    gateway: ModelGateway


class MultiProviderModelGateway:
    """Select a governed gateway per role and optionally run an explicitly configured fallback."""

    def __init__(
        self,
        router: RoleModelRouter,
        bindings: Mapping[str, ProviderBinding],
        store: TeamRoutingStore,
        on_switch: Callable[[RouteDecision, RouteDecision], None] | None = None,
    ) -> None:
        self.router = router
        self.bindings = dict(bindings)
        self.store = store
        self.on_switch = on_switch

    def generate(
        self,
        request: ModelRequest,
        *,
        project_id: str | None = None,
        task_route: ModelRoute | None = None,
        max_retries: int = 0,
    ) -> tuple[ModelResponse, RouteDecision, bool]:
        decision = self.router.resolve(
            request.role_type, project_id=project_id, task_route=task_route
        )
        try:
            response = self._call(decision, request, max_retries)
            self.store.record_call(
                decision,
                response,
                success=True,
                structured_output_success=response.structured_output is not None,
            )
            return response, decision, False
        except ProviderError:
            self.store.record_call(decision, None, success=False)
            if not decision.fallback_provider_id or not decision.fallback_model:
                raise
            fallback = decision.model_copy(
                update={
                    "provider_id": decision.fallback_provider_id,
                    "model": decision.fallback_model,
                    "fallback_provider_id": None,
                    "fallback_model": None,
                }
            )
            if self.on_switch:
                self.on_switch(decision, fallback)
            response = self._call(fallback, request, max_retries)
            self.store.record_call(
                fallback,
                response,
                success=True,
                structured_output_success=response.structured_output is not None,
            )
            return response, fallback, True

    def _call(
        self, decision: RouteDecision, request: ModelRequest, max_retries: int
    ) -> ModelResponse:
        binding = self.bindings.get(decision.provider_id)
        if binding is None:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "WAITING_FOR_PROVIDER_CREDENTIAL",
                provider=decision.provider_id,
                model=decision.model,
            )
        routed = request.model_copy(
            update={
                "model": decision.model,
                "max_output_tokens": min(request.max_output_tokens, decision.token_budget),
                "metadata": {
                    **request.metadata,
                    "provider_id": decision.provider_id,
                },
            }
        )
        return binding.gateway.generate(routed, max_retries=max_retries)


class MultiProviderRoutedProvider:
    """ModelProvider-compatible role router for the existing governed ModelGateway.

    This is the production bridge used by the task runtime. Provider-specific objects stay
    behind this boundary, and the outer ModelGateway remains the single budget ledger.
    """

    provider_name = "multi_provider"

    def __init__(
        self,
        router: RoleModelRouter,
        providers: Mapping[str, Any],
        store: TeamRoutingStore,
        *,
        project_id: str | None = None,
        route: ResolvedRuntimeRoute | None = None,
    ) -> None:
        self.router = router
        self.providers = dict(providers)
        self.store = store
        self.project_id = project_id
        self.route = route
        self.call_count = 0

    def _route_for_request(self, request: ModelRequest) -> ResolvedRuntimeRoute:
        if self.route is not None:
            return self.route
        return self.router.resolve_route(request.role_type, project_id=self.project_id)

    def cache_identity(self, request: ModelRequest) -> dict[str, Any]:
        """Expose adapter identity without reselecting provider/model semantics."""
        route = self._route_for_request(request)
        provider = self.providers.get(route.provider_id)
        if provider is None:
            return {
                "provider_id": route.provider_id,
                "provider_name": route.provider_id,
                "selected_model": route.model_id,
                "protocol_family": "unknown",
            }
        cache_identity = getattr(provider, "cache_identity", None)
        raw = cache_identity(request) if callable(cache_identity) else {}
        identity = dict(raw) if isinstance(raw, Mapping) else {}
        identity.update(
            {
                "provider_id": route.provider_id,
                "provider_name": identity.get("provider_name")
                or getattr(provider, "provider_name", route.provider_id),
                "selected_model": route.model_id,
            }
        )
        return identity

    def estimate_usage(self, request: ModelRequest):
        route = self._route_for_request(request)
        provider = self.providers.get(route.provider_id)
        if provider is None:
            from app.gateway.contracts import UsageEstimate

            return UsageEstimate()
        routed = request.model_copy(
            update={
                "model": route.model_id,
                "metadata": {
                    **request.metadata,
                    "provider_id": route.provider_id,
                },
            }
        )
        return provider.estimate_usage(routed)

    def generate(self, request: ModelRequest) -> ModelResponse:
        route = self._route_for_request(request)
        decision = RouteDecision(
            role=route.role or request.role_type,
            provider_id=route.provider_id,
            model=route.model_id,
            source=route.source,
            fallback_provider_id=route.fallback_provider_id,
            fallback_model=route.fallback_model_id,
            token_budget=route.token_budget,
            cost_budget=route.cost_budget,
        )
        try:
            response = self._call(route, request)
            response.provider_id = route.provider_id
            self.store.record_call(
                decision,
                response,
                success=True,
                structured_output_success=response.structured_output is not None,
            )
            return response
        except ProviderError:
            self.store.record_call(decision, None, success=False)
            if not route.fallback_provider_id or not route.fallback_model_id:
                raise
            fallback = ResolvedRuntimeRoute(
                provider_id=route.fallback_provider_id,
                model_id=route.fallback_model_id,
                source=f"{route.source}:fallback",
                role=route.role,
                token_budget=route.token_budget,
                cost_budget=route.cost_budget,
            )
            fallback_decision = RouteDecision(
                role=fallback.role or request.role_type,
                provider_id=fallback.provider_id,
                model=fallback.model_id,
                source=fallback.source,
                token_budget=fallback.token_budget,
                cost_budget=fallback.cost_budget,
            )
            response = self._call(fallback, request)
            response.provider_id = fallback.provider_id
            self.store.record_call(
                fallback_decision,
                response,
                success=True,
                structured_output_success=response.structured_output is not None,
            )
            return response

    def _call(self, route: ResolvedRuntimeRoute, request: ModelRequest) -> ModelResponse:
        provider = self.providers.get(route.provider_id)
        if provider is None:
            raise ProviderError(
                ProviderErrorCode.CONFIG_ERROR,
                "WAITING_FOR_PROVIDER_CREDENTIAL",
                provider=route.provider_id,
                model=route.model_id,
            )
        routed_metadata = {
            **request.metadata,
            "provider_id": route.provider_id,
        }
        prepared_provider = str(
            (request.metadata.get("cache_intelligence") or {}).get("provider_id", "")
        )
        if prepared_provider and prepared_provider != route.provider_id:
            routed_metadata.pop("cache_provider_payload", None)
            routed_metadata.pop("cache_intelligence", None)
        routed = request.model_copy(
            update={
                "model": route.model_id,
                "max_output_tokens": min(request.max_output_tokens, route.token_budget),
                "metadata": routed_metadata,
            }
        )
        self._enforce_role_cost_budget(
            RouteDecision(
                role=route.role or request.role_type,
                provider_id=route.provider_id,
                model=route.model_id,
                source=route.source,
                token_budget=route.token_budget,
                cost_budget=route.cost_budget,
            ),
            provider,
            routed,
        )
        self.call_count += 1
        response = provider.generate(routed)
        response.provider_id = route.provider_id
        cache_identity = getattr(provider, "cache_identity", None)
        raw_identity = cache_identity(routed) if callable(cache_identity) else {}
        identity = dict(raw_identity) if isinstance(raw_identity, Mapping) else {}
        identity.update(
            {
                "provider_id": route.provider_id,
                "provider_name": identity.get("provider_name")
                or getattr(provider, "provider_name", route.provider_id),
                "selected_model": route.model_id,
            }
        )
        response.provider_identity = identity
        return response

    def _enforce_role_cost_budget(
        self, decision: RouteDecision, provider: Any, request: ModelRequest
    ) -> None:
        if decision.cost_budget is None:
            return
        estimate = provider.estimate_usage(request)
        if estimate.estimated_max_cost is None:
            raise ProviderError(
                ProviderErrorCode.BUDGET_INSUFFICIENT,
                "role cost budget cannot be verified because provider cost is unavailable",
                provider=decision.provider_id,
                model=decision.model,
            )
        profiles = [item for item in self.store.performance() if item.role == decision.role]
        spent = (
            None
            if any(item.calls and item.cost is None for item in profiles)
            else sum(item.cost or 0.0 for item in profiles)
        )
        if spent is None or spent + estimate.estimated_max_cost > decision.cost_budget:
            raise ProviderError(
                ProviderErrorCode.BUDGET_INSUFFICIENT,
                "role cost budget insufficient for model call",
                provider=decision.provider_id,
                model=decision.model,
            )

    def health_check(self) -> ProviderHealth:
        statuses = [provider.health_check() for provider in self.providers.values()]
        healthy = [item for item in statuses if item.status == "healthy"]
        return ProviderHealth(
            status="healthy" if healthy else "unavailable",
            provider=self.provider_name,
            model="role-routed",
            message=f"{len(healthy)}/{len(statuses)} configured providers healthy",
        )


class ProviderHealthService:
    """Read-only health composition. It never issues a model call by itself."""

    @staticmethod
    def status(*, configured: bool, health: str, invocation_status: str = "not_tested") -> str:
        if not configured:
            return "WAITING_FOR_PROVIDER_CREDENTIAL"
        if invocation_status == "success":
            return "REAL_READY"
        if health in {"healthy", "configured"}:
            return "CONFIGURED_NOT_INVOKED"
        return health.upper()


class SupervisorArbitrator:
    """Deterministic conflict order; model confidence never outranks evidence."""

    PRIORITY = {
        "deterministic_safety": 5,
        "tests": 4,
        "evidence": 3,
        "reviewer": 2,
        "executor_confidence": 1,
    }

    @classmethod
    def choose(cls, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not candidates:
            raise ValueError("at least one arbitration candidate is required")
        return max(candidates, key=lambda item: cls.PRIORITY.get(str(item.get("source")), 0))
