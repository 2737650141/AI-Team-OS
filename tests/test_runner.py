"""运行器测试（M2 语义）。"""

from __future__ import annotations

from pathlib import Path

from app.runner import run_task


def test_run_github_compare_team(tmp_path: Path) -> None:
    """GT-01 offline：github_compare_team 全流程完成，Reviewer 通过后才完成。"""
    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.final_result is not None
    assert "evidence_index" in report.state.final_result
    assert report.tool_call_count >= 2  # researcher 的 s1/s2 工具调用
    assert len(report.state.subtasks) == 3
    assert all(s.runtime_status == "passed" for s in report.state.subtasks)
    assert report.state.rework_count == 0


def test_run_planning_invalid_failure(tmp_path: Path) -> None:
    """Plan 校验失败（超预算）：failed/planning_invalid，状态写回 checkpoint 可读。"""
    report = run_task(
        "scenario:over-budget",
        token_budget=50,
        cost_budget=0.01,
        data_dir=tmp_path / "data",
    )
    assert report.status == "failed"
    assert report.state.failure_code == "planning_invalid"
    assert report.state.final_result is not None


def test_run_vague_goal_pauses_for_clarification(tmp_path: Path) -> None:
    """GT-02：模糊目标触发澄清 interrupt（paused + pending_clarification_id）。"""
    report = run_task(
        "vague_goal",
        token_budget=10000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "paused"
    assert report.state.pending_clarification_id is not None
    assert report.state.paused_from_status == "created"
