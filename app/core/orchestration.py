"""Bounded orchestration contracts for PRODUCT-02.

The model may propose capabilities and dependencies. Deterministic runtime code owns
task shape, subtask limits, executable role selection, and fallback simplification.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.core.complexity import TaskComplexity


class TaskShape(str, Enum):
    READ_ONLY_RESEARCH = "read_only_research"
    CODE_ANALYSIS = "code_analysis"
    CODE_CHANGE = "code_change"
    WINDOWS_ACTION = "windows_action"
    MULTI_STEP_DELIVERY = "multi_step_delivery"
    DIRECT_RESPONSE = "direct_response"


class Capability(str, Enum):
    RESEARCH = "research"
    CODE_CHANGE = "code_change"
    VERIFICATION = "verification"
    WINDOWS_ACTION = "windows_action"
    ANALYSIS = "analysis"


SUBTASK_LIMITS: dict[TaskComplexity, tuple[int, int]] = {
    TaskComplexity.TRIVIAL: (0, 1),
    TaskComplexity.SIMPLE: (1, 2),
    TaskComplexity.STANDARD: (2, 4),
    TaskComplexity.COMPLEX: (3, 6),
}


def classify_task_shape(goal: str) -> TaskShape:
    text = (goal or "").lower()
    if text.startswith("sandbox_"):
        return TaskShape.CODE_CHANGE
    if text.startswith("scenario:"):
        return TaskShape.MULTI_STEP_DELIVERY
    if "github_compare" in text:
        return TaskShape.READ_ONLY_RESEARCH
    no_write = any(
        marker in text
        for marker in (
            "不要改代码",
            "别改代码",
            "不修改代码",
            "只给修改方案",
            "仅输出方案",
            "只分析",
            "no write",
        )
    )
    code_markers = ("代码", "模块", "依赖", "测试", "bug", "patch", "pytest", "修复")
    change_markers = ("修复", "修改", "实施", "直接修", "apply", "patch", "fix")
    windows_markers = ("窗口", "记事本", "桌面", "点击", "输入", "windows")
    research_markers = ("github", "研究", "调研", "搜索", "找 ", "找几个", "对比")
    # M7-A4B: background scheduling is managed through the governed tool.
    schedule_markers = (
        "秒后", "分钟后", "小时后", "每天", "每隔", "每30秒", "每1小时",
        "后台任务", "后台", "提醒我", "定时", "暂停", "继续", "取消", "别再看",
        "别再检查", "有哪些后台", "schedule", "定时任务", "预约",
    )
    if any(marker in text for marker in schedule_markers):
        return TaskShape.READ_ONLY_RESEARCH
    if any(marker in text for marker in windows_markers):
        return TaskShape.WINDOWS_ACTION
    if "github" in text and any(marker in text for marker in research_markers):
        return TaskShape.READ_ONLY_RESEARCH
    if any(marker in text for marker in code_markers):
        if no_write or not any(marker in text for marker in change_markers):
            return TaskShape.CODE_ANALYSIS
        return TaskShape.CODE_CHANGE
    if any(marker in text for marker in research_markers):
        return TaskShape.READ_ONLY_RESEARCH
    if any(marker in text for marker in ("然后", "最后", "方案", "交付", "多步")):
        return TaskShape.MULTI_STEP_DELIVERY
    return TaskShape.DIRECT_RESPONSE


def capabilities_for_shape(shape: TaskShape) -> list[Capability]:
    mapping = {
        TaskShape.DIRECT_RESPONSE: [],
        TaskShape.READ_ONLY_RESEARCH: [Capability.RESEARCH],
        TaskShape.CODE_ANALYSIS: [Capability.ANALYSIS, Capability.RESEARCH],
        TaskShape.CODE_CHANGE: [
            Capability.RESEARCH,
            Capability.CODE_CHANGE,
            Capability.VERIFICATION,
        ],
        TaskShape.WINDOWS_ACTION: [Capability.WINDOWS_ACTION, Capability.VERIFICATION],
        TaskShape.MULTI_STEP_DELIVERY: [
            Capability.RESEARCH,
            Capability.CODE_CHANGE,
            Capability.VERIFICATION,
        ],
    }
    return mapping[shape]


class PlanningEnvelope(BaseModel):
    task_complexity: TaskComplexity
    task_shape: TaskShape
    allowed_capabilities: list[Capability]
    max_subtasks: int = Field(ge=0, le=6)
    min_subtasks: int = Field(ge=0, le=6)
    allowed_subtask_types: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    token_budget: int = Field(gt=0)
    max_model_calls: int = Field(gt=0, le=20)
    plan_repair_budget: Literal[1] = 1

    @classmethod
    def for_task(
        cls,
        goal: str,
        complexity: TaskComplexity,
        available_tools: list[str],
        token_budget: int,
        max_model_calls: int,
    ) -> "PlanningEnvelope":
        shape = classify_task_shape(goal)
        if shape is TaskShape.DIRECT_RESPONSE and complexity is not TaskComplexity.TRIVIAL:
            # A non-trivial request still needs an executable bounded capability.
            # Defaulting to read-only research is the safest useful envelope;
            # leaving it as DIRECT_RESPONSE would make min_subtasks impossible.
            shape = TaskShape.READ_ONLY_RESEARCH
        min_subtasks, max_subtasks = SUBTASK_LIMITS[complexity]
        if shape in {TaskShape.READ_ONLY_RESEARCH, TaskShape.CODE_ANALYSIS}:
            # Read-only Standard work normally needs at most two specialists,
            # while Complex work still needs room for evidence synthesis.
            max_subtasks = min(max_subtasks, max(2, min_subtasks))
        return cls(
            task_complexity=complexity,
            task_shape=shape,
            allowed_capabilities=capabilities_for_shape(shape),
            max_subtasks=max_subtasks,
            min_subtasks=min_subtasks,
            allowed_subtask_types=[c.value for c in capabilities_for_shape(shape)],
            available_tools=sorted(available_tools),
            token_budget=token_budget,
            max_model_calls=min(max_model_calls, 20),
        )


class RoleRouter:
    """Map capabilities to executable roles; governance roles never enter exec_subtask."""

    _ROLE_BY_CAPABILITY = {
        Capability.RESEARCH: "researcher",
        Capability.ANALYSIS: "researcher",
        Capability.CODE_CHANGE: "executor",
        # Reviewer is a graph gate, not an executable subtask role.
        Capability.VERIFICATION: "executor",
        Capability.WINDOWS_ACTION: "executor",
    }

    def route(self, capability: Capability | str) -> str:
        normalized = capability if isinstance(capability, Capability) else Capability(capability)
        return self._ROLE_BY_CAPABILITY[normalized]

    def validate(self, capability: Capability | str, assigned_role: str) -> bool:
        return self.route(capability) == assigned_role


def deterministic_simplification(plan, envelope: PlanningEnvelope):
    """Keep the earliest dependency-valid bounded slice without inventing work."""
    if len(plan.subtasks) <= envelope.max_subtasks:
        return plan
    kept = plan.subtasks[: envelope.max_subtasks]
    kept_ids = {item.subtask_id for item in kept}
    for item in kept:
        item.dependencies = [dep for dep in item.dependencies if dep in kept_ids]
    return plan.model_copy(update={"subtasks": kept})


def calibrate_plan_capabilities(plan, envelope: PlanningEnvelope):
    """Correct obvious capability-label drift without inventing new work.

    Providers sometimes label downstream test/report nodes as ``code_change``
    even though an ancestor already produced and tested the implementation.
    Those nodes are verification consumers and must reuse evidence rather than
    start another patch-generation turn.
    """
    if envelope.task_shape is not TaskShape.CODE_CHANGE:
        return plan
    by_id = {item.subtask_id: item for item in plan.subtasks}

    def has_change_ancestor(item, seen: set[str] | None = None) -> bool:
        visited = set(seen or ())
        for dependency_id in item.dependencies:
            if dependency_id in visited:
                continue
            visited.add(dependency_id)
            dependency = by_id.get(dependency_id)
            if dependency is None:
                continue
            if dependency.capability_required == Capability.CODE_CHANGE.value:
                return True
            if has_change_ancestor(dependency, visited):
                return True
        return False

    verification_markers = (
        "验证",
        "验收",
        "运行测试",
        "测试结果",
        "修复报告",
        "reviewer",
        "verify",
        "verification",
        "test result",
        "report",
    )
    for item in plan.subtasks:
        text = " ".join(
            [item.title, item.objective, item.expected_output, *item.acceptance_criteria]
        ).lower()
        if (
            item.capability_required == Capability.CODE_CHANGE.value
            and item.dependencies
            and has_change_ancestor(item)
            and any(marker in text for marker in verification_markers)
        ):
            item.capability_required = Capability.VERIFICATION.value
            item.task_type = Capability.VERIFICATION.value
    return plan


def bounded_plan_for_shape(goal: str, envelope: PlanningEnvelope):
    """Generic deterministic recovery plan driven only by shape/capabilities."""
    from app.core.schemas import Plan, SubtaskSpec

    each_budget = max(500, envelope.token_budget // max(envelope.min_subtasks, 2))
    if envelope.task_shape is TaskShape.READ_ONLY_RESEARCH:
        github = (
            "github_search_repositories" in envelope.available_tools and "github" in goal.lower()
        )
        tool = "github_search_repositories" if github else "local_list_directory"
        if "fixture_repo_lookup" in envelope.available_tools and not github:
            tool = "fixture_repo_lookup"
        refs = (
            ["fixture_repo_lookup:langgraph", "fixture_repo_lookup:crewai"]
            if tool == "fixture_repo_lookup"
            else []
        )
        subtasks = [
            SubtaskSpec(
                subtask_id="research_discovery",
                title="收集直接证据",
                objective=goal + "；先收集满足数量要求的直接证据。",
                dependencies=[],
                assigned_role="researcher",
                capability_required="research",
                input_refs=refs[:1],
                expected_output="带证据的候选与事实",
                acceptance_criteria=["结果非空", "关键结论有 evidence"],
                required_tools=[tool],
                token_budget=each_budget,
                tool_call_budget=3,
            ),
            SubtaskSpec(
                subtask_id="research_comparison",
                title="独立比较与风险分析",
                objective=goal + "；从优点、缺点、风险和可借鉴设计四方面形成比较。",
                dependencies=["research_discovery"],
                assigned_role="researcher",
                capability_required="research",
                input_refs=refs[1:2],
                expected_output="结构化比较和建议",
                acceptance_criteria=["包含优缺点", "建议与证据一致"],
                required_tools=[tool],
                token_budget=each_budget,
                tool_call_budget=3,
            ),
        ]
        if envelope.min_subtasks >= 3:
            subtasks.append(
                SubtaskSpec(
                    subtask_id="research_synthesis",
                    title="综合证据并形成交付",
                    objective=goal + "；综合前述证据，明确决策、局限与落地顺序。",
                    dependencies=["research_discovery", "research_comparison"],
                    assigned_role="researcher",
                    capability_required="research",
                    input_refs=["research_discovery", "research_comparison"],
                    expected_output="可追溯的最终研究交付",
                    acceptance_criteria=["结论可追溯", "包含局限与实施建议"],
                    required_tools=[],
                    token_budget=each_budget,
                    tool_call_budget=1,
                )
            )
        return Plan(goal=goal, subtasks=subtasks)
    if envelope.task_shape is TaskShape.CODE_ANALYSIS:
        tool = (
            "local_list_directory"
            if "local_list_directory" in envelope.available_tools
            else "fixture_repo_lookup"
        )
        subtasks = [
            SubtaskSpec(
                subtask_id="analysis_dependencies",
                title="依赖与边界分析",
                objective=goal + "；只读分析依赖、入口与边界，不得写文件。",
                dependencies=[],
                assigned_role="researcher",
                capability_required="analysis",
                input_refs=["local_list_directory:."]
                if tool == "local_list_directory"
                else ["fixture_repo_lookup:langgraph"],
                expected_output="依赖关系分析",
                acceptance_criteria=["分析非空", "无写操作"],
                required_tools=[tool],
                token_budget=each_budget,
                tool_call_budget=3,
            ),
            SubtaskSpec(
                subtask_id="analysis_risks",
                title="风险与修改方案",
                objective=goal + "；只读识别潜在风险并给出优先级方案，不得改代码。",
                dependencies=[],
                assigned_role="researcher",
                capability_required="analysis",
                input_refs=["local_list_directory:app"]
                if tool == "local_list_directory"
                else ["fixture_repo_lookup:crewai"],
                expected_output="风险清单和修改方案",
                acceptance_criteria=["风险有依据", "只给方案不写入"],
                required_tools=[tool],
                token_budget=each_budget,
                tool_call_budget=3,
            ),
        ]
        if envelope.min_subtasks >= 3:
            subtasks.append(
                SubtaskSpec(
                    subtask_id="analysis_synthesis",
                    title="综合分析并输出方案",
                    objective=goal + "；综合依赖与风险证据，输出只读实施方案。",
                    dependencies=["analysis_dependencies", "analysis_risks"],
                    assigned_role="researcher",
                    capability_required="analysis",
                    input_refs=["analysis_dependencies", "analysis_risks"],
                    expected_output="带证据、优先级和局限的只读方案",
                    acceptance_criteria=["证据可追溯", "不产生写操作"],
                    required_tools=[],
                    token_budget=each_budget,
                    tool_call_budget=1,
                )
            )
        return Plan(goal=goal, subtasks=subtasks)
    return None
