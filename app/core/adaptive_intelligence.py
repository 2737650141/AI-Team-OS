"""M7-A1 adaptive capability, agent, skill, and routing foundation.

This module is deterministic and deliberately independent from LangGraph orchestration. It
contains only contracts, registries, scoped capability checks, model selection policy, and
provider-neutral reasoning policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

from app.core.complexity import TaskComplexity, classify_task


class RegistryHandle:
    def __init__(self, dispose: Callable[[], None]) -> None:
        self._dispose = dispose
        self._disposed = False

    @property
    def disposed(self) -> bool:
        return self._disposed

    def dispose(self) -> None:
        if not self._disposed:
            self._disposed = True
            self._dispose()


class CapabilitySpec(BaseModel):
    id: str
    version: str = "1.0"
    description: str = ""
    provider_id: str = "builtin"
    provenance: Literal["builtin", "open-source-reference", "user-installed"] = "builtin"
    metadata: dict[str, Any] = Field(default_factory=dict)
    available: bool = True


class CapabilityRequirement(BaseModel):
    id: str
    minimum_version: str | None = None
    required: bool = True


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> RegistryHandle:
        if spec.id in self._items:
            raise ValueError(f"duplicate capability: {spec.id}")
        self._items[spec.id] = spec

        def dispose() -> None:
            self._items.pop(spec.id, None)

        return RegistryHandle(dispose)

    def unregister(self, capability_id: str) -> bool:
        return self._items.pop(capability_id, None) is not None

    def get(self, capability_id: str) -> CapabilitySpec:
        try:
            return self._items[capability_id]
        except KeyError as exc:
            raise KeyError(f"unknown capability: {capability_id}") from exc

    def has(self, capability_id: str) -> bool:
        return capability_id in self._items and self._items[capability_id].available

    def require(self, capability_id: str) -> CapabilitySpec:
        spec = self.get(capability_id)
        if not spec.available:
            raise UnsupportedCapabilityError(f"UNSUPPORTED_CAPABILITY: {capability_id}")
        return spec

    def all(self) -> list[CapabilitySpec]:
        return sorted(self._items.values(), key=lambda item: item.id)


class RoutingMode(str, Enum):
    AUTO = "auto"
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


class ReasoningEffort(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DEEP = "deep"


_REASONING_ORDER = [
    ReasoningEffort.NONE,
    ReasoningEffort.LOW,
    ReasoningEffort.MEDIUM,
    ReasoningEffort.HIGH,
    ReasoningEffort.DEEP,
]


class ExecutionMode(str, Enum):
    MODEL = "model"
    TOOL_ONLY = "tool_only"


class TaskProfile(BaseModel):
    task_kind: str = "general"
    complexity: TaskComplexity = TaskComplexity.STANDARD
    required_capabilities: tuple[str, ...] = ()
    preferred_capabilities: tuple[str, ...] = ()
    latency_priority: float = 0.5
    cost_priority: float = 0.5
    quality_priority: float = 0.5
    reliability_priority: float = 0.5
    context_need: int = 0
    tool_intensity: int = 0
    reasoning_need: ReasoningEffort = ReasoningEffort.MEDIUM
    routing_mode: RoutingMode = RoutingMode.BALANCED
    explicit_model: str | None = None
    explicit_provider_id: str | None = None
    agent_id: str | None = None


class TaskProfiler:
    """Metadata/keyword-only profiler. It never calls a model."""

    def profile(
        self,
        goal: str,
        *,
        agent_id: str | None = None,
        required_capabilities: Iterable[str] = (),
        **metadata: Any,
    ) -> TaskProfile:
        complexity = classify_task(goal)
        text = (goal or "").lower()
        required = list(dict.fromkeys(required_capabilities))
        if any(marker in text for marker in ("vision", "image", "screenshot", "截图")):
            required.append("vision.inspect")
        if any(marker in text for marker in ("crawl", "crawler", "抓取", "爬取")):
            task_kind = "tool_only"
            reasoning = ReasoningEffort.NONE
        elif any(marker in text for marker in ("architecture", "debug", "设计", "调试")):
            task_kind = "architecture"
            reasoning = ReasoningEffort.HIGH
        elif any(marker in text for marker in ("format", "rewrite", "改写", "润色")):
            task_kind = "formatting"
            reasoning = ReasoningEffort.LOW
        elif complexity is TaskComplexity.TRIVIAL:
            task_kind = "greeting"
            reasoning = ReasoningEffort.NONE
        elif complexity is TaskComplexity.SIMPLE:
            task_kind = "simple"
            reasoning = ReasoningEffort.LOW
        else:
            task_kind = "general"
            reasoning = ReasoningEffort.MEDIUM
        return TaskProfile(
            task_kind=metadata.get("task_kind", task_kind),
            complexity=complexity,
            required_capabilities=tuple(dict.fromkeys(required)),
            preferred_capabilities=tuple(metadata.get("preferred_capabilities", ())),
            latency_priority=float(metadata.get("latency_priority", 0.5)),
            cost_priority=float(metadata.get("cost_priority", 0.5)),
            quality_priority=float(metadata.get("quality_priority", 0.5)),
            reliability_priority=float(metadata.get("reliability_priority", 0.5)),
            reasoning_need=metadata.get("reasoning_need", reasoning),
            routing_mode=metadata.get("routing_mode", RoutingMode.BALANCED),
            context_need=int(metadata.get("context_need", 0)),
            tool_intensity=int(metadata.get("tool_intensity", 0)),
            agent_id=agent_id,
            explicit_model=metadata.get("explicit_model"),
            explicit_provider_id=metadata.get("explicit_provider_id"),
        )


class ModelProfile(BaseModel):
    provider_id: str
    model_id: str
    capabilities: frozenset[str] = frozenset({"llm.chat"})
    reasoning_levels: frozenset[ReasoningEffort] = frozenset(
        {ReasoningEffort.NONE, ReasoningEffort.LOW, ReasoningEffort.MEDIUM}
    )
    native_reasoning_mapping: dict[ReasoningEffort, str] = Field(default_factory=dict)
    quality: float = 0.5
    latency: float = 0.5
    cost: float = 0.5
    reliability: float = 0.5
    context_tokens: int = 0
    provenance: str = "builtin"

    def supports_reasoning(self, effort: ReasoningEffort) -> bool:
        return effort in self.reasoning_levels

    def native_reasoning_value(self, effort: ReasoningEffort) -> str | None:
        return self.native_reasoning_mapping.get(effort)


class RoutingDecision(BaseModel):
    agent_id: str | None
    provider_id: str | None
    model: str | None
    reasoning_effort: ReasoningEffort
    required_capabilities: tuple[str, ...] = ()
    matched_capabilities: tuple[str, ...] = ()
    routing_mode: RoutingMode
    execution_mode: ExecutionMode
    safe_reason: str
    score: float | None = None
    fallback_candidates: tuple[str, ...] = ()
    decision_version: str = "m7-a1.v1"


class UnsupportedCapabilityError(ValueError):
    code = "UNSUPPORTED_CAPABILITY"


class ReasoningEscalationPolicy(BaseModel):
    max_escalations: int = 2

    def escalate(
        self,
        current: ReasoningEffort,
        reason: str,
        previous_escalations: int = 0,
    ) -> ReasoningEffort:
        allowed = {
            "capability_conflict",
            "material_contradiction",
            "low_confidence",
            "invalid_structured_result",
        }
        if reason not in allowed or previous_escalations >= self.max_escalations:
            return current
        index = min(_REASONING_ORDER.index(current) + 1, len(_REASONING_ORDER) - 1)
        return _REASONING_ORDER[index]

    def downgrade(self, current: ReasoningEffort, target: ReasoningEffort) -> ReasoningEffort:
        return (
            target if _REASONING_ORDER.index(target) <= _REASONING_ORDER.index(current) else current
        )


class TaskModelRouter:
    def __init__(self, models: Iterable[ModelProfile] = ()) -> None:
        self._models = list(models)

    def route(self, profile: TaskProfile, *, agent_id: str | None = None) -> RoutingDecision:
        if profile.task_kind in {"crawl", "fetch", "parse", "tool_only"}:
            return RoutingDecision(
                agent_id=agent_id or profile.agent_id,
                provider_id=None,
                model=None,
                reasoning_effort=ReasoningEffort.NONE,
                required_capabilities=profile.required_capabilities,
                matched_capabilities=profile.required_capabilities,
                routing_mode=profile.routing_mode,
                execution_mode=ExecutionMode.TOOL_ONLY,
                safe_reason=(
                    "This step uses deterministic tools and does not require a language model."
                ),
            )
        candidates = [model for model in self._models if self._eligible(model, profile)]
        if profile.explicit_provider_id:
            candidates = [
                model for model in candidates if model.provider_id == profile.explicit_provider_id
            ]
            if profile.explicit_model and not candidates:
                raise UnsupportedCapabilityError(
                    f"MODEL_PROVIDER_MISMATCH: provider={profile.explicit_provider_id}"
                )
        if profile.explicit_model:
            candidates = [model for model in candidates if model.model_id == profile.explicit_model]
            if not candidates:
                raise UnsupportedCapabilityError(
                    "MODEL_CAPABILITY_MISMATCH: "
                    f"model={profile.explicit_model} "
                    f"required={','.join(profile.required_capabilities)}"
                )
        if not candidates:
            raise UnsupportedCapabilityError(
                f"{UnsupportedCapabilityError.code}: "
                f"required={','.join(profile.required_capabilities)}"
            )
        scored = sorted(
            ((self._score(model, profile), model) for model in candidates),
            key=lambda pair: (-pair[0], pair[1].provider_id, pair[1].model_id),
        )
        score, selected = scored[0]
        return RoutingDecision(
            agent_id=agent_id or profile.agent_id,
            provider_id=selected.provider_id,
            model=selected.model_id,
            reasoning_effort=profile.reasoning_need,
            required_capabilities=profile.required_capabilities,
            matched_capabilities=tuple(
                sorted(set(profile.required_capabilities) | set(profile.preferred_capabilities))
            ),
            routing_mode=profile.routing_mode,
            execution_mode=ExecutionMode.MODEL,
            safe_reason=(
                f"Selected a model matching the required capabilities for {profile.task_kind}."
            ),
            score=score,
            fallback_candidates=tuple(model.model_id for _, model in scored[1:]),
        )

    @staticmethod
    def _eligible(model: ModelProfile, profile: TaskProfile) -> bool:
        return (
            all(capability in model.capabilities for capability in profile.required_capabilities)
            and model.context_tokens >= profile.context_need
            and model.supports_reasoning(profile.reasoning_need)
        )

    @staticmethod
    def _score(model: ModelProfile, profile: TaskProfile) -> float:
        mode = profile.routing_mode
        if profile.task_kind in {"greeting", "formatting", "simple"}:
            quality_weight = 0.7
        elif profile.task_kind in {"architecture", "expert"}:
            quality_weight = 4.0
        elif mode is RoutingMode.QUALITY:
            quality_weight = 4.0
        else:
            quality_weight = 0.8 if mode is RoutingMode.ECONOMY else 1.0
        cost_weight = (
            1.5 if mode is RoutingMode.ECONOMY else 0.6 if mode is RoutingMode.QUALITY else 1.0
        )
        latency_weight = 1.3 if mode is RoutingMode.ECONOMY else 0.8
        return (
            quality_weight * model.quality
            + profile.reliability_priority * model.reliability
            - cost_weight * model.cost
            - latency_weight * model.latency
        )


class AgentSpec(BaseModel):
    id: str
    display_name: str
    description: str = ""
    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    preferred_model_profile: str | None = None
    default_reasoning: ReasoningEffort = ReasoningEffort.MEDIUM
    permission_requirements: tuple[str, ...] = ()
    version: str = "1.0"
    provenance: Literal["builtin", "open-source-reference", "user-installed"] = "builtin"
    enabled: bool = True


class AgentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> RegistryHandle:
        if spec.id in self._items:
            raise ValueError(f"duplicate agent: {spec.id}")
        self._items[spec.id] = spec

        def dispose() -> None:
            self._items.pop(spec.id, None)

        return RegistryHandle(dispose)

    def resolve(self, agent_id: str) -> AgentSpec:
        spec = self._items.get(agent_id)
        if spec is None or not spec.enabled:
            raise KeyError(f"unknown or disabled agent: {agent_id}")
        return spec

    def all(self) -> list[AgentSpec]:
        return sorted(self._items.values(), key=lambda item: item.id)


class SkillSpec(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    license: str = "internal"
    provenance: Literal["builtin", "open-source-reference", "user-installed"] = "builtin"
    required_capabilities: tuple[str, ...] = ()
    optional_capabilities: tuple[str, ...] = ()
    compatible_agents: tuple[str, ...] = ()
    instructions_ref: str | None = None
    examples_ref: str | None = None


class SkillRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> RegistryHandle:
        if spec.id in self._items:
            raise ValueError(f"duplicate skill: {spec.id}")
        self._items[spec.id] = spec

        def dispose() -> None:
            self._items.pop(spec.id, None)

        return RegistryHandle(dispose)

    def discover(self, agent_id: str | None = None) -> list[SkillSpec]:
        return [
            skill
            for skill in sorted(self._items.values(), key=lambda item: item.id)
            if not agent_id or not skill.compatible_agents or agent_id in skill.compatible_agents
        ]

    def resolve(self, skill_id: str) -> SkillSpec:
        return self._items[skill_id]


@dataclass(frozen=True)
class AgentScope:
    agent_id: str
    visible_capabilities: frozenset[str] = frozenset()
    visible_tools: frozenset[str] = frozenset()
    allowed_tools: frozenset[str] = frozenset()
    skills: frozenset[str] = frozenset()
    permission_ceiling: str = "safe"

    def can_use_tool(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools and tool_name in self.visible_tools

    def require_tool(self, tool_name: str) -> None:
        if not self.can_use_tool(tool_name):
            raise PermissionError(f"tool not allowed in agent scope: {tool_name}")


def default_capability_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability_id, description in {
        "llm.chat": "Generate text through a model",
        "llm.reasoning": "Use provider-supported reasoning controls",
        "web.search": "Search web or repository sources",
        "web.fetch": "Fetch a web resource",
        "web.crawl": "Crawl web resources through a future crawler provider",
        "code.read": "Read source code",
        "code.edit": "Propose or apply code changes",
        "code.execute": "Run governed code/test commands",
        "filesystem.read": "Read governed files",
        "filesystem.write": "Write through governed tools",
        "research.synthesize": "Synthesize evidence-backed research",
        "computer.control": "Control the local computer through permissioned tools",
        "security.analysis": "Analyze security properties",
        "vision.inspect": "Inspect visual input",
    }.items():
        registry.register(CapabilitySpec(id=capability_id, description=description))
    return registry


def default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for spec in (
        AgentSpec(id="supervisor", display_name="Supervisor"),
        AgentSpec(id="planner", display_name="Planner", required_capabilities=("llm.chat",)),
        AgentSpec(
            id="researcher",
            display_name="Researcher",
            required_capabilities=("research.synthesize",),
            allowed_tools=("web.fetch", "web.search", "filesystem.read"),
        ),
        AgentSpec(
            id="executor",
            display_name="Executor",
            required_capabilities=("code.edit", "filesystem.write"),
            allowed_tools=("filesystem.read", "filesystem.write", "code.execute"),
        ),
        AgentSpec(id="reviewer", display_name="Reviewer", required_capabilities=("llm.chat",)),
        AgentSpec(
            id="crawler",
            display_name="Crawler",
            required_capabilities=("web.crawl", "web.fetch"),
            allowed_tools=("web.fetch",),
            enabled=False,
        ),
    ):
        registry.register(spec)
    return registry
