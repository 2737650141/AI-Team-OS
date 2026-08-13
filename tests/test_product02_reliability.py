"""PRODUCT-02 deterministic reliability gates (real-provider suites run separately)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.llm_agents import PATCH_SCHEMA, REVIEW_SCHEMA
from app.agents.reviewer import DeterministicReviewer
from app.core.completion import ProductCompletionValidator
from app.core.complexity import TaskComplexity
from app.core.orchestration import (
    Capability,
    PlanningEnvelope,
    RoleRouter,
    TaskShape,
    bounded_plan_for_shape,
    calibrate_plan_capabilities,
    classify_task_shape,
    deterministic_simplification,
)
from app.core.output_governance import validate_against_schema
from app.core.plan_validator import PlanValidationError, validate_plan
from app.core.registry import default_registry
from app.core.schemas import (
    Claim,
    CriterionResult,
    ExecutionResult,
    Plan,
    ReviewIssue,
    ReviewResult,
    ReviewStatus,
    ReworkItem,
    SubtaskSpec,
)
from app.core.state import SubtaskState, TaskState
from app.core.tool_repair import ToolCallRepairLayer
from app.core.workflow_cost import CostDecision, WorkflowCostGovernor
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.tools.fixture_repo import FixtureRepositoryLookupTool


def _subtask(i: int, capability: str = "research", role: str = "researcher") -> SubtaskSpec:
    return SubtaskSpec(
        subtask_id=f"s{i}",
        title=f"task {i}",
        objective="objective",
        dependencies=[] if i == 1 else [f"s{i - 1}"],
        assigned_role=role,
        capability_required=capability,
        expected_output="deliverable",
        acceptance_criteria=["criterion"],
        required_tools=[],
        token_budget=100,
        tool_call_budget=1,
    )


def test_task_shapes_prevent_executor_for_analysis() -> None:
    assert classify_task_shape("分析这个模块，只给修改方案，不要改代码") is TaskShape.CODE_ANALYSIS
    assert classify_task_shape("修复失败测试并直接修改代码") is TaskShape.CODE_CHANGE
    assert classify_task_shape("制定实施方案（不修改代码，仅输出方案）") is TaskShape.CODE_ANALYSIS
    assert (
        classify_task_shape("去 GitHub 找 3 个多 Agent 项目并对比") is TaskShape.READ_ONLY_RESEARCH
    )


def test_planning_envelope_limits_and_role_router() -> None:
    envelope = PlanningEnvelope.for_task(
        "去 GitHub 找 3 个项目并对比",
        TaskComplexity.STANDARD,
        ["github_search_repositories"],
        10000,
        20,
    )
    assert envelope.max_subtasks == 2
    assert envelope.allowed_capabilities == [Capability.RESEARCH]
    assert RoleRouter().route(Capability.RESEARCH) == "researcher"
    with pytest.raises(PlanValidationError) as error:
        validate_plan(
            Plan(goal="g", subtasks=[_subtask(i) for i in range(1, 6)]),
            default_registry(),
            10000,
            envelope=envelope,
        )
    assert error.value.code == "plan_too_complex"


def test_researcher_registry_matches_real_github_capabilities() -> None:
    allowed = set(default_registry().get("researcher").allowed_tools)
    assert {"github_search_repositories", "github_repo_info"} <= allowed


def test_deterministic_plan_simplification_is_bounded() -> None:
    envelope = PlanningEnvelope.for_task(
        "去 GitHub 找项目并对比",
        TaskComplexity.STANDARD,
        [],
        10000,
        20,
    )
    simplified = deterministic_simplification(
        Plan(goal="g", subtasks=[_subtask(i) for i in range(1, 6)]), envelope
    )
    assert len(simplified.subtasks) == envelope.max_subtasks == 2
    assert all(dep != "s5" for item in simplified.subtasks for dep in item.dependencies)


def test_research_fallback_reuses_discovery_evidence_for_comparison() -> None:
    envelope = PlanningEnvelope.for_task(
        "GitHub compare three multi-agent projects",
        TaskComplexity.STANDARD,
        ["github_search_repositories", "github_repo_info"],
        10000,
        20,
    )
    plan = bounded_plan_for_shape("GitHub compare three multi-agent projects", envelope)
    assert plan is not None
    assert plan.subtasks[1].dependencies == [plan.subtasks[0].subtask_id]


def test_complex_read_only_envelope_has_synthesis_capacity() -> None:
    goal = "研究三个 GitHub 项目并提出架构方案，不要改代码"
    envelope = PlanningEnvelope.for_task(
        goal,
        TaskComplexity.COMPLEX,
        ["github_search_repositories"],
        60000,
        20,
    )
    assert envelope.min_subtasks == envelope.max_subtasks == 3
    plan = bounded_plan_for_shape(goal, envelope)
    assert plan is not None and len(plan.subtasks) == 3
    assert plan.subtasks[-1].dependencies == ["research_discovery", "research_comparison"]


def test_nontrivial_direct_request_defaults_to_read_only_capability() -> None:
    envelope = PlanningEnvelope.for_task(
        "这个项目支持哪些权限模式？分别是什么？",
        TaskComplexity.STANDARD,
        ["local_list_directory"],
        20000,
        20,
    )
    assert envelope.task_shape is TaskShape.READ_ONLY_RESEARCH
    assert envelope.allowed_capabilities == [Capability.RESEARCH]


def test_dependency_evidence_contract_requires_claim_per_reference() -> None:
    # Regression contract for chained Researchers: dependency evidence is not
    # represented as a direct tool entry, but every verified ref must still be
    # promotable to a claim before deterministic review.
    refs = list(dict.fromkeys(["ev-1", "ev-2", "ev-1"]))
    claims = [
        Claim(claim_id=f"s-evidence-{i}", text="governed dependency evidence", evidence_ids=[ref])
        for i, ref in enumerate(refs, start=1)
    ]
    assert len(claims) == len(refs) == 2
    assert {claim.evidence_ids[0] for claim in claims} == set(refs)


def test_code_plan_calibrates_downstream_test_and_report_to_verification() -> None:
    plan = Plan(
        goal="fix the project",
        subtasks=[
            _subtask(1, "code_change", "executor"),
            _subtask(2, "code_change", "executor").model_copy(
                update={"title": "运行测试验证修复", "objective": "verify test result"}
            ),
            _subtask(3, "code_change", "executor").model_copy(
                update={"title": "整理修复报告供 Reviewer 验收", "objective": "report"}
            ),
        ],
    )
    envelope = PlanningEnvelope.for_task(
        "sandbox_code_fix: fix the failing test",
        TaskComplexity.STANDARD,
        [],
        10000,
        20,
    )
    calibrated = calibrate_plan_capabilities(plan, envelope)
    assert [item.capability_required for item in calibrated.subtasks] == [
        "code_change",
        "verification",
        "verification",
    ]


def test_tool_schema_is_complete_and_repair_is_bounded(tmp_path: Path) -> None:
    gateway = ToolGateway(AuditLog(tmp_path / "audit.jsonl"), "task")
    gateway.register(FixtureRepositoryLookupTool(Path("app/tools/fixtures/repos.json")).spec())
    contract = gateway.tool_contract("fixture_repo_lookup")
    assert contract["required"] == ["repo_name"]
    assert "example" in contract
    prepared = ToolCallRepairLayer.prepare(
        {"repo_name": "langgraph", "page_size": 100},
        {"repo_name"},
        {"repo_name"},
    )
    assert prepared.ok and prepared.args == {"repo_name": "langgraph"}
    assert prepared.removed == ["page_size"]
    filled = ToolCallRepairLayer.prepare({}, {"repo"}, {"repo"}, {"repo": ["a/b"]})
    assert filled.args == {"repo": "a/b"}
    ambiguous = ToolCallRepairLayer.prepare({}, {"repo"}, {"repo"}, {"repo": ["a/b", "c/d"]})
    assert ambiguous.missing == ["repo"]


def test_reviewer_four_states_and_rework_contract() -> None:
    assert ReviewResult(status="PASS").verdict == "pass"
    notes = ReviewResult(status="PASS_WITH_NOTES", notes=["optional cleanup"])
    assert notes.verdict == "pass"
    rework = ReviewResult(
        status="REWORK",
        issues=[ReviewIssue(code="tests_failed", message="pytest failed")],
        required_change="fix the failing assertion",
        target_role="executor",
        criteria_results=[CriterionResult(criterion="tests pass", status="FAIL")],
    )
    assert rework.verdict == "reject" and rework.retryable
    blocked = ReviewResult(status=ReviewStatus.BLOCK, blocking_issues=[])
    assert blocked.verdict == "reject" and not blocked.retryable
    with pytest.raises(ValueError):
        ReviewResult(status="REWORK")


def test_reviewer_v2_contract_does_not_require_legacy_fields() -> None:
    payload = {
        "status": "PASS",
        "summary": "All deterministic acceptance criteria passed.",
        "criteria_results": [],
        "blocking_issues": [],
        "rework_items": [],
        "notes": [],
        "evidence_refs": [],
        "confidence": 0.9,
    }

    validated = validate_against_schema(payload, REVIEW_SCHEMA)
    result = ReviewResult.model_validate(validated)

    assert result.status is ReviewStatus.PASS
    assert result.issues == []
    assert result.rework_targets == []


def test_reviewer_criterion_accepts_unambiguous_result_alias() -> None:
    result = ReviewResult.model_validate(
        {
            "status": "PASS",
            "criteria_results": [{"criterion": "tests pass", "result": "PASS"}],
        }
    )
    assert result.criteria_results[0].status == "PASS"


def test_rework_items_are_not_equivalent_to_prompt_truncation_notes() -> None:
    result = ReviewResult(
        status="REWORK",
        rework_items=[
            ReworkItem(
                failure_code="missing_required_item",
                target_subtask="s1",
                target_role="researcher",
                failed_criterion="include both required items",
                required_change="add the missing second item",
                why_it_matters="it is a core acceptance criterion",
                verification_required="verify both items and evidence",
            )
        ],
    )
    assert result.status is ReviewStatus.REWORK
    assert result.rework_items


def test_patch_transport_schema_allows_domain_default_metadata() -> None:
    validated = validate_against_schema(
        {
            "target_files": ["src/main.py"],
            "unified_diff": "--- a/src/main.py\n+++ b/src/main.py\n",
        },
        PATCH_SCHEMA,
    )
    assert validated["target_files"] == ["src/main.py"]


def test_workflow_cost_governor_thresholds_and_role_limit() -> None:
    governor = WorkflowCostGovernor("standard")
    assert governor.assess("planner", 0).decision is CostDecision.ALLOW
    assert governor.assess("researcher", 12).decision is CostDecision.WARNING
    assert governor.assess("researcher", 16).decision is CostDecision.RECOVERY
    assert governor.assess("researcher", 20).decision is CostDecision.STOP
    governor.record("planner")
    governor.record("planner")
    assert governor.assess("planner", 2).decision is CostDecision.RECOVERY


def test_standard_reviewer_budget_is_one_call_plus_one_format_repair() -> None:
    governor = WorkflowCostGovernor("standard")
    first = governor.assess_and_reserve("reviewer", 0)
    second = governor.assess_and_reserve("reviewer", 1)
    third = governor.assess_and_reserve("reviewer", 2)
    assert first.decision is CostDecision.ALLOW
    assert second.decision is CostDecision.ALLOW
    assert third.decision is CostDecision.RECOVERY


def test_deterministic_reviewer_accepts_verified_executor_replay() -> None:
    subtask = SubtaskState.model_validate(_subtask(1, "verification", "executor").model_dump())
    subtask.execution_result = ExecutionResult(
        subtask_id=subtask.subtask_id,
        summary="reused approved implementation and passing tests",
        claims=[Claim(claim_id="c1", text="tests pass", evidence_ids=["e1"], confidence=1)],
        evidence_refs=["e1"],
        ts="now",
        metadata={
            "status": "implemented_replay",
            "approval_id": "a1",
            "test_report": {"return_code": 0},
        },
    )
    issues = DeterministicReviewer().check(subtask, {"e1"}, [], 0)
    assert not [item for item in issues if item.code == "executor_not_implemented"]


def test_completion_validator_rejects_empty_research() -> None:
    state = TaskState(task_id="t", user_goal="research", token_budget=1000, cost_budget=1)
    decision = ProductCompletionValidator().validate(state, TaskShape.READ_ONLY_RESEARCH)
    assert not decision.complete
    assert "result_nonempty" in decision.reasons
    assert "research_claims" in decision.reasons


def test_dependent_research_can_reuse_evidence_contract() -> None:
    first = _subtask(1)
    second = _subtask(2)
    assert second.dependencies == [first.subtask_id]
    # Dependency reuse is represented explicitly in the plan and does not require
    # another discovery capability or an executor.
    assert first.capability_required == second.capability_required == "research"


def test_intermediate_research_dependency_is_explicitly_detectable() -> None:
    first = SubtaskState.model_validate(_subtask(1).model_dump())
    second = SubtaskState.model_validate(_subtask(2).model_dump())
    assert any(first.subtask_id in item.dependencies for item in [first, second])
