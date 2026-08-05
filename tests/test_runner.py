"""运行器测试（CLI 底层逻辑）。"""

from __future__ import annotations

from pathlib import Path

from app.runner import run_task


def test_run_task_echo(tmp_path: Path) -> None:
    report = run_task(
        "hello",
        token_budget=5000,
        cost_budget=0.5,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    assert report.state.final_result is not None
    assert report.usage["tokens"] > 0
    assert report.call_count == 1


def test_run_task_budget_failure(tmp_path: Path) -> None:
    """极小预算：任务以 failed(budget_exceeded) 终止，不越预算。"""
    report = run_task(
        "hello world, this is a longer goal",
        token_budget=50,
        cost_budget=0.01,
        data_dir=tmp_path / "data",
    )
    assert report.status == "failed"
    assert report.state.failure_code == "budget_exceeded"
    assert report.usage["tokens"] <= 50
