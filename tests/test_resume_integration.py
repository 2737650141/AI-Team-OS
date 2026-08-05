"""跨进程 Checkpoint 恢复集成测试（003-A 二/三：真实 Runtime，非实验脚本）。"""

from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.resume import ResumePayload

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _cli(*args: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, "-m", "app.cli", *args, "--data-dir", str(data_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )


def _parse(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _max_checkpoint_step(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT metadata FROM checkpoints").fetchall()
    conn.close()
    steps = [json.loads(r[0]).get("step", -1) for r in rows]
    return max(steps)


def test_cross_process_pause_resume(tmp_path: Path) -> None:
    """进程 A 创建并暂停 → 退出 → 进程 B 恢复 → completed（003-A 二 12 项全部断言）。"""
    data_dir = tmp_path / "data"

    # 进程 A：run --pause-after agent（节点边界暂停后进程退出）
    run_out = _cli(
        "run",
        "github_compare_mock",
        "--pause-after",
        "agent",
        "--budget-tokens",
        "5000",
        "--budget-cost",
        "1.0",
        data_dir=data_dir,
    )
    run_info = _parse(run_out.stdout)
    assert run_info["status"] == "paused"
    run_id = run_info["run_id"]
    task_id = run_info["task_id"]
    assert run_id and task_id
    step_paused = _max_checkpoint_step(data_dir / "checkpoints.db")

    # 进程 B：status（暂停后快照）
    paused_snapshot = _parse(_cli("status", run_id, data_dir=data_dir).stdout)
    assert paused_snapshot["status"] == "paused"
    assert paused_snapshot["task_id"] == task_id
    assert paused_snapshot["run_id"] == run_id
    assert paused_snapshot["tool_call_count"] == "1"  # 已成功工具不丢失

    # 进程 B：resume → completed
    resume_out = _cli("resume", run_id, data_dir=data_dir)
    resume_info = _parse(resume_out.stdout)
    assert resume_info["status"] == "completed"
    assert resume_info["task_id"] == task_id  # task_id 保持不变
    assert resume_info["run_id"] == run_id  # run_id 保持不变
    assert resume_info["tool_call_count"] == "1"  # 已成功的工具不重复执行
    usage_resumed = ast.literal_eval(resume_info["usage"])
    assert usage_resumed["tokens"] > 0  # token_usage 不清零
    step_resumed = _max_checkpoint_step(data_dir / "checkpoints.db")
    assert step_resumed > step_paused  # checkpoint 链递增

    # 进程 C：最终状态验证
    final = _parse(_cli("status", run_id, data_dir=data_dir).stdout)
    assert final["status"] == "completed"
    assert final["task_id"] == task_id
    assert final["run_id"] == run_id
    assert final["tool_call_count"] == "1"
    usage_final = ast.literal_eval(final["usage"])
    assert usage_final["tokens"] > 0
    assert usage_final["tokens"] >= usage_resumed["tokens"]


def test_resume_payload_rejects_none_action() -> None:
    """003-A 三：恢复值禁止为 None；默认 action=continue；Schema 校验生效。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResumePayload.model_validate({"action": None})
    assert ResumePayload().action == "continue"
    assert ResumePayload(action="go").action == "go"
    assert ResumePayload(action="go").model_dump()["action"] == "go"


def test_resume_missing_run_rejected(tmp_path: Path) -> None:
    """恢复不存在的 run_id 必须明确报错。"""
    from app.runner import resume_task

    with pytest.raises(KeyError, match="run not found"):
        resume_task("no-such-run", data_dir=tmp_path / "data")


def test_resume_completed_run_rejected(tmp_path: Path) -> None:
    """对已 completed 的 run 恢复必须拒绝（前置校验，review should-fix）。"""
    from app.runner import resume_task, run_task

    report = run_task(
        "already-done",
        token_budget=5000,
        cost_budget=1.0,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    with pytest.raises(RuntimeError, match="not paused"):
        resume_task(report.run_id, data_dir=tmp_path / "data")


def test_budget_failure_persisted_to_checkpoint(tmp_path: Path) -> None:
    """预算失败状态写回 checkpoint：跨进程 status 可读到 failed（review should-fix）。"""
    from app.runner import run_task, status_task

    report = run_task(
        "expensive goal that will blow the tiny budget",
        token_budget=50,
        cost_budget=0.01,
        data_dir=tmp_path / "data",
    )
    assert report.status == "failed"
    snapshot = status_task(report.run_id, data_dir=tmp_path / "data")
    assert snapshot.status == "failed"
    assert snapshot.state.failure_code == "budget_exceeded"
