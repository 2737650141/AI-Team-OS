"""PRODUCT-01 修复验证（纠偏令 020）。

覆盖：
1. plan_validator 可执行角色约束（role_not_executable）——根因修复。
2. TaskComplexityClassifier 分级（TRIVIAL/SIMPLE/STANDARD/COMPLEX）。
3. SIMPLE 快速路径：单 researcher、无 LLM Planner、跳过 Reviewer Gate。
4. TRIVIAL 快速路径：空计划直接完成。
5. ReworkProgressGuard：连续无进展 → Supervisor replan（非盲重试）。
6. Reviewer 结构化拒绝字段（required_change / target_role / retryable）。
7. failure_signature 稳定性。
8. STANDARD 任务回归：github_compare_team 仍 3 subtasks 完成。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.complexity import TaskComplexity, classify_task
from app.core.plan_validator import EXECUTABLE_ROLES, PlanValidationError, validate_plan
from app.core.registry import default_registry
from app.core.rework_guard import ReworkProgressGuard, failure_signature
from app.core.schemas import Plan, ReviewIssue, SubtaskSpec
from app.runner import run_task

GOAL_GITHUB_POPULAR = "帮我找几个热门的 GitHub AI Agent 项目"


def _plan_with_role(role: str) -> Plan:
    return Plan(
        goal="g",
        subtasks=[
            SubtaskSpec(
                subtask_id="st1",
                title="t",
                objective="o",
                dependencies=[],
                assigned_role=role,
                input_refs=[],
                expected_output="r",
                acceptance_criteria=["a"],
                required_tools=[],
                token_budget=500,
                tool_call_budget=1,
            )
        ],
    )


# ---------- 1. plan_validator 可执行角色约束 ----------
def test_plan_validator_rejects_non_executable_role() -> None:
    """Planner 分配 registry 中存在但运行时不可执行的角色 → role_not_executable。"""
    registry = default_registry()
    with pytest.raises(PlanValidationError) as exc:
        validate_plan(_plan_with_role("planner"), registry, 10000)
    assert exc.value.code == "role_not_executable"
    with pytest.raises(PlanValidationError):
        validate_plan(_plan_with_role("supervisor"), registry, 10000)
    with pytest.raises(PlanValidationError):
        validate_plan(_plan_with_role("reviewer"), registry, 10000)


def test_plan_validator_accepts_executable_roles() -> None:
    registry = default_registry()
    for role in EXECUTABLE_ROLES:
        validate_plan(_plan_with_role(role), registry, 10000)  # 不抛异常


# ---------- 2. TaskComplexityClassifier ----------
def test_classify_task_levels() -> None:
    assert classify_task("现在几点") == TaskComplexity.TRIVIAL
    assert classify_task("介绍一下你自己。") == TaskComplexity.TRIVIAL
    assert classify_task("这个项目主要用了什么技术？") == TaskComplexity.SIMPLE
    assert classify_task("conversation_followup: 对比最近结果") == TaskComplexity.SIMPLE
    assert classify_task(GOAL_GITHUB_POPULAR) == TaskComplexity.SIMPLE
    assert classify_task("github_compare_team") == TaskComplexity.STANDARD
    assert classify_task("scenario:always-reject") == TaskComplexity.STANDARD
    assert classify_task("sandbox_REAL01") == TaskComplexity.STANDARD
    assert classify_task("研究三个 GitHub 项目并提出架构方案") == TaskComplexity.COMPLEX
    assert classify_task("先别改代码，先提出方案然后执行") == TaskComplexity.COMPLEX
    assert classify_task("调研三种记忆方案，写技术选型报告") == TaskComplexity.COMPLEX
    assert classify_task("制定下一阶段里程碑并按风险排序") == TaskComplexity.COMPLEX


# ---------- 3. SIMPLE 快速路径 ----------
def test_simple_task_fast_path(tmp_path: Path) -> None:
    """SIMPLE 任务：单 researcher 子任务完成，无 LLM Planner、跳过 Reviewer Gate。"""
    report = run_task(
        GOAL_GITHUB_POPULAR,
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.complexity == "simple"
    assert report.state.review_required is False
    active = [s for s in report.state.subtasks if not s.superseded]
    assert len(active) == 1
    assert all(s.assigned_role == "researcher" for s in active)
    assert all(s.runtime_status == "passed" for s in active)
    assert report.tool_call_count == 2  # 两个 fixture 仓库查询
    assert report.state.rework_count == 0


# ---------- 4. TRIVIAL 快速路径 ----------
def test_trivial_task_completes_without_subtasks(tmp_path: Path) -> None:
    report = run_task(
        "现在几点",
        token_budget=5000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.complexity == "trivial"
    assert report.state.review_required is False
    active = [s for s in report.state.subtasks if not s.superseded]
    assert active == []


# ---------- 5. ReworkProgressGuard → Supervisor replan ----------
def test_rework_no_progress_triggers_replan(tmp_path: Path) -> None:
    """always-reject 场景：连续无进展 → replan（而非纯 rework 计数），上限后失败。"""
    data_dir = tmp_path / "data"
    report = run_task(
        "scenario:always-reject",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=data_dir,
    )
    assert report.status == "failed"
    assert report.state.failure_code == "rework_limit_exceeded"
    assert report.state.replan_count > 0  # 走 replan 路径（纠偏令 017/018）
    # 事件流必须包含 replan 轨迹（EventStore 为进程单例，从全局 store 查询）
    from app.core.events import get_store

    store = get_store()
    assert store is not None
    conn = __import__("sqlite3").connect(str(store._db_path))
    rows = conn.execute(
        "SELECT event_type FROM events WHERE run_id=? AND event_type IN "
        "('replan_triggered','supervisor_replanned')",
        (report.run_id,),
    ).fetchall()
    conn.close()
    types = {r[0] for r in rows}
    assert "replan_triggered" in types


def test_normal_rework_still_targeted_not_replan(tmp_path: Path) -> None:
    """reject-once 场景：进展性返工不应触发 replan（guard 不误伤）。"""
    report = run_task(
        "scenario:reject-once",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.replan_count == 0


# ---------- 6. Reviewer 结构化拒绝字段 ----------
def test_reviewer_structured_reject_fields(tmp_path: Path) -> None:
    from app.agents.reviewer import FakeReviewer
    from app.core.schemas import Claim, ExecutionResult
    from app.core.state import SubtaskState

    subtask = SubtaskState(
        subtask_id="x1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=[],
        token_budget=100,
        tool_call_budget=1,
    )
    subtask.execution_result = ExecutionResult(
        subtask_id="x1",
        summary="s",
        claims=[Claim(claim_id="c1", text="无证据结论", evidence_ids=[])],
        ts="t",
    )
    result = FakeReviewer().review(
        subtask, [ReviewIssue(code="claim_without_evidence", message="无证据", subtask_id="x1")]
    )
    assert result.verdict == "reject"
    assert result.required_change  # 具体修改要求
    assert result.target_role == "researcher"  # 返工角色
    assert result.retryable is True
    # always-reject：不可重试（必须 replan）
    result2 = FakeReviewer("review_always_reject").review(subtask, [])
    assert result2.verdict == "reject"
    assert result2.retryable is False


# ---------- 7. failure_signature 稳定性 ----------
def test_failure_signature_stability() -> None:
    from app.core.schemas import Claim, ExecutionResult

    res = ExecutionResult(
        subtask_id="st1",
        summary="s",
        claims=[Claim(claim_id="c1", text="t", evidence_ids=["e"])],
        ts="t",
    )
    sig1 = failure_signature("st1", "researcher", res, ["unknown_evidence"], ["st1"])
    sig2 = failure_signature("st1", "researcher", res, ["unknown_evidence"], ["st1"])
    assert sig1 == sig2  # 相同失败 → 相同签名
    sig3 = failure_signature("st1", "researcher", res, ["no_content"], ["st1"])
    assert sig1 != sig3  # 失败原因变化 → 签名变化


def test_rework_guard_detects_no_progress() -> None:
    guard = ReworkProgressGuard(max_identical=2)
    sig = "st1|researcher|abc|unknown_evidence|st1"
    assert guard.has_no_progress([sig]) is False
    assert guard.has_no_progress([sig, sig]) is True
    assert guard.has_no_progress([sig, "st1|researcher|def|x|y"]) is False


# ---------- 8. STANDARD 任务回归 ----------
def test_standard_task_unchanged(tmp_path: Path) -> None:
    """The offline fixture keeps its historical 3-node plan and completes review.

    PRODUCT-02 minimum bounded plans apply to real-provider production work;
    deterministic fake scenarios remain stable for cache/rework regressions.
    """
    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.complexity == "standard"
    active = [s for s in report.state.subtasks if not s.superseded]
    assert len(active) == 3
    assert all(s.runtime_status == "passed" for s in active)
    final = json.loads(report.state.final_result)
    assert final["decision"] == "accept"
