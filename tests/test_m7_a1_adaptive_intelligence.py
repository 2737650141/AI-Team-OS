from __future__ import annotations

import pytest

from app.core.adaptive_intelligence import (
    AgentRegistry,
    AgentScope,
    AgentSpec,
    CapabilityRegistry,
    CapabilitySpec,
    ExecutionMode,
    ModelProfile,
    ReasoningEffort,
    RoutingMode,
    SkillRegistry,
    SkillSpec,
    TaskModelRouter,
    TaskProfiler,
    UnsupportedCapabilityError,
    default_capability_registry,
)


def models() -> list[ModelProfile]:
    return [
        ModelProfile(
            provider_id="p-fast",
            model_id="fast-model",
            capabilities=frozenset({"llm.chat"}),
            reasoning_levels=frozenset({ReasoningEffort.NONE, ReasoningEffort.LOW}),
            quality=0.4,
            latency=0.1,
            cost=0.1,
            context_tokens=16_000,
        ),
        ModelProfile(
            provider_id="p-balanced",
            model_id="balanced-model",
            capabilities=frozenset({"llm.chat", "llm.reasoning", "research.synthesize"}),
            reasoning_levels=frozenset(ReasoningEffort),
            quality=0.7,
            latency=0.4,
            cost=0.4,
            context_tokens=64_000,
        ),
        ModelProfile(
            provider_id="p-reasoning",
            model_id="reasoning-model",
            capabilities=frozenset({"llm.chat", "llm.reasoning", "research.synthesize"}),
            reasoning_levels=frozenset(
                {ReasoningEffort.MEDIUM, ReasoningEffort.HIGH, ReasoningEffort.DEEP}
            ),
            quality=0.95,
            latency=0.8,
            cost=0.9,
            context_tokens=128_000,
        ),
        ModelProfile(
            provider_id="p-vision",
            model_id="vision-model",
            capabilities=frozenset({"llm.chat", "vision.inspect"}),
            reasoning_levels=frozenset({ReasoningEffort.LOW, ReasoningEffort.MEDIUM}),
            quality=0.8,
            latency=0.5,
            cost=0.6,
            context_tokens=64_000,
        ),
    ]


def test_cap01_to_cap07_registry_and_dispose() -> None:
    registry = CapabilityRegistry()
    handle = registry.register(CapabilitySpec(id="web.fetch", provider_id="provider-a"))
    assert registry.get("web.fetch").provider_id == "provider-a"
    with pytest.raises(ValueError):
        registry.register(CapabilitySpec(id="web.fetch"))
    handle.dispose()
    assert not registry.has("web.fetch")
    registry.register(CapabilitySpec(id="vision.inspect", available=False))
    with pytest.raises(UnsupportedCapabilityError, match="UNSUPPORTED_CAPABILITY"):
        registry.require("vision.inspect")
    assert default_capability_registry().has("llm.chat")


def test_agent_and_skill_registration_are_reversible() -> None:
    agents = AgentRegistry()
    agent_handle = agents.register(
        AgentSpec(
            id="researcher",
            display_name="Researcher",
            required_capabilities=("research.synthesize",),
        )
    )
    assert agents.resolve("researcher").required_capabilities == ("research.synthesize",)
    skills = SkillRegistry()
    skill_handle = skills.register(
        SkillSpec(
            id="research",
            name="Research",
            compatible_agents=("researcher",),
            required_capabilities=("web.fetch",),
        )
    )
    assert [item.id for item in skills.discover("researcher")] == ["research"]
    skill_handle.dispose()
    agent_handle.dispose()
    assert agents.all() == [] and skills.discover() == []


def test_scope_visibility_and_execution_are_both_enforced() -> None:
    scope = AgentScope(
        agent_id="researcher",
        visible_tools=frozenset({"web.fetch"}),
        allowed_tools=frozenset({"web.fetch"}),
    )
    scope.require_tool("web.fetch")
    with pytest.raises(PermissionError):
        scope.require_tool("computer.control")


def test_tool_gateway_rejects_scope_forbidden_execution(tmp_path) -> None:
    from app.gateway.audit import AuditLog
    from app.gateway.tool_gateway import ToolGateway
    from app.tools.spec import RiskLevel, ToolSpec

    gateway = ToolGateway(AuditLog(tmp_path / "audit.jsonl"), task_id="t1")
    gateway.register(
        ToolSpec(
            name="web.fetch",
            description="fetch",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=lambda: {"ok": True},
        )
    )
    gateway.register(
        ToolSpec(
            name="computer.control",
            description="control",
            input_schema={},
            risk_level=RiskLevel.DANGEROUS,
            read_only=False,
            handler=lambda: {"ok": True},
        )
    )
    gateway.set_agent_scope(
        AgentScope(
            agent_id="crawler",
            visible_tools=frozenset({"web.fetch"}),
            allowed_tools=frozenset({"web.fetch"}),
        )
    )
    assert "computer.control" not in gateway.available_tools()
    assert gateway.invoke("web.fetch", {}).ok
    denied = gateway.invoke("computer.control", {})
    assert not denied.ok and denied.status == "blocked"

    profile = TaskProfiler().profile("你好")
    assert profile.task_kind == "greeting" and profile.reasoning_need is ReasoningEffort.NONE
    assert TaskProfiler().profile("你好") == profile


def test_router_matrix_and_provider_identity() -> None:
    router = TaskModelRouter(models())
    assert router.route(TaskProfiler().profile("你好")).reasoning_effort is ReasoningEffort.NONE
    assert router.route(TaskProfiler().profile("润色这句话")).model == "fast-model"
    assert (
        router.route(TaskProfiler().profile("普通研究"), agent_id="researcher").model
        == "balanced-model"
    )
    complex_profile = TaskProfiler().profile("架构设计和调试")
    assert router.route(complex_profile).model == "reasoning-model"
    vision = TaskProfiler().profile("检查 screenshot", required_capabilities=("vision.inspect",))
    decision = router.route(vision)
    assert decision.model == "vision-model" and decision.provider_id == "p-vision"
    economy = TaskProfiler().profile("普通研究", routing_mode=RoutingMode.ECONOMY)
    assert router.route(economy).model == "balanced-model"
    quality = TaskProfiler().profile("普通研究", routing_mode=RoutingMode.QUALITY)
    assert router.route(quality).model == "reasoning-model"


def test_router_fail_loud_explicit_and_tool_only() -> None:
    router = TaskModelRouter(models())
    with pytest.raises(UnsupportedCapabilityError, match="UNSUPPORTED_CAPABILITY"):
        router.route(
            TaskProfiler().profile(
                "vision",
                required_capabilities=("vision.inspect",),
                reasoning_need=ReasoningEffort.HIGH,
            )
        )
    with pytest.raises(UnsupportedCapabilityError, match="MODEL_CAPABILITY_MISMATCH"):
        router.route(
            TaskProfiler().profile(
                "检查 screenshot",
                required_capabilities=("vision.inspect",),
                explicit_model="fast-model",
            )
        )
    tool = router.route(TaskProfiler().profile("raw fetch", task_kind="tool_only"))
    assert (
        tool.execution_mode is ExecutionMode.TOOL_ONLY
        and tool.model is None
        and tool.reasoning_effort is ReasoningEffort.NONE
    )


def test_reasoning_policy_escalates_only_allowed_reasons() -> None:
    from app.core.adaptive_intelligence import ReasoningEscalationPolicy

    policy = ReasoningEscalationPolicy(max_escalations=2)
    assert policy.escalate(ReasoningEffort.LOW, "capability_conflict") is ReasoningEffort.MEDIUM
    assert policy.escalate(ReasoningEffort.LOW, "timeout") is ReasoningEffort.LOW
    assert policy.escalate(ReasoningEffort.HIGH, "low_confidence", 2) is ReasoningEffort.HIGH
    assert policy.downgrade(ReasoningEffort.HIGH, ReasoningEffort.LOW) is ReasoningEffort.LOW


def test_default_agent_registry_contains_disabled_crawler_fixture() -> None:
    from app.core.adaptive_intelligence import default_agent_registry

    registry = default_agent_registry()
    assert {item.id for item in registry.all()} >= {
        "supervisor",
        "planner",
        "researcher",
        "executor",
        "reviewer",
        "crawler",
    }
    with pytest.raises(KeyError):
        registry.resolve("crawler")


def test_router_respects_explicit_provider_identity_and_reasoning_mapping() -> None:
    router = TaskModelRouter(
        [
            ModelProfile(
                provider_id="gateway-a",
                model_id="gpt-5.6-sol",
                capabilities=frozenset({"llm.chat", "llm.reasoning"}),
                reasoning_levels=frozenset(ReasoningEffort),
                native_reasoning_mapping={ReasoningEffort.HIGH: "high"},
                quality=0.9,
                latency=0.5,
                cost=0.5,
                context_tokens=64_000,
            ),
            ModelProfile(
                provider_id="gateway-b",
                model_id="gpt-5.6-sol",
                capabilities=frozenset({"llm.chat"}),
                reasoning_levels=frozenset({ReasoningEffort.LOW}),
                quality=0.8,
                latency=0.3,
                cost=0.2,
                context_tokens=64_000,
            ),
        ]
    )
    profile = TaskProfiler().profile(
        "复杂研究",
        required_capabilities=("llm.reasoning",),
        explicit_provider_id="gateway-a",
    )
    decision = router.route(profile)
    assert decision.provider_id == "gateway-a"
    assert decision.model == "gpt-5.6-sol"
    assert decision.reasoning_effort is ReasoningEffort.MEDIUM

    profile = TaskProfiler().profile("复杂研究")
    router = TaskModelRouter(models())
    assert router.route(profile) == router.route(profile)
    skill = SkillSpec(
        id="x", name="X", instructions_ref="skills/x/SKILL.md", examples_ref="skills/x/examples"
    )
    assert skill.instructions_ref and skill.examples_ref
