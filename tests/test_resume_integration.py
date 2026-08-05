"""跨进程恢复集成测试（M2：澄清 interrupt 恢复；003-A 兼容层回归）。"""

from __future__ import annotations

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


def test_cross_process_clarify_resume(tmp_path: Path) -> None:
    """进程 A run vague_goal → 澄清 interrupt 暂停并退出 → 进程 B resume → completed。

    断言：task_id/run_id 不变、clarification_history 正确、澄清后继续 Planner 流程。
    """
    data_dir = tmp_path / "data"

    # 进程 A：run vague_goal（澄清挂起）
    run_out = _cli("run", "vague_goal", "--budget-tokens", "10000", data_dir=data_dir)
    run_info = _parse(run_out.stdout)
    assert run_info["status"] == "paused"
    run_id = run_info["run_id"]
    task_id = run_info["task_id"]
    assert run_id and task_id

    # 进程 B：status 快照（paused + 澄清挂起）
    snapshot = _parse(_cli("status", run_id, data_dir=data_dir).stdout)
    assert snapshot["status"] == "paused"
    assert snapshot["task_id"] == task_id
    assert snapshot["run_id"] == run_id

    # 进程 B：resume --clarification
    resume_out = _cli(
        "resume",
        run_id,
        "--clarification",
        "调研 LangGraph 与 CrewAI 的选型对比",
        data_dir=data_dir,
    )
    resume_info = _parse(resume_out.stdout)
    assert resume_info["status"] == "completed"
    assert resume_info["task_id"] == task_id  # task_id 保持不变
    assert resume_info["run_id"] == run_id  # run_id 保持不变

    # 进程 C：trace 验证 clarification_history 与澄清后流程
    trace_out = _cli("trace", run_id, data_dir=data_dir)
    import json

    trace = json.loads(trace_out.stdout)
    assert trace["current_status"] == "completed"
    assert len(trace["clarification_history"]) == 1
    assert trace["clarification_history"][0]["answer"] == "调研 LangGraph 与 CrewAI 的选型对比"
    assert "澄清" in (trace["clarified_goal"] or "")
    assert len(trace["subtasks"]) == 3
    assert all(s["runtime_status"] == "passed" for s in trace["subtasks"])


def test_resume_payload_rejects_none_action() -> None:
    """003-A 三：恢复值禁止为 None；默认 action=continue；Schema 校验生效。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResumePayload.model_validate({"action": None})
    assert ResumePayload().action == "continue"
    assert ResumePayload(action="go").action == "go"


def test_resume_missing_run_rejected(tmp_path: Path) -> None:
    """恢复不存在的 run_id 必须明确报错。"""
    from app.runner import resume_task

    with pytest.raises(KeyError, match="run not found"):
        resume_task("no-such-run", data_dir=tmp_path / "data")


def test_resume_completed_run_rejected(tmp_path: Path) -> None:
    """对已 completed 的 run 恢复必须拒绝（前置校验）。"""
    from app.runner import resume_task, run_task

    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=1.0,
        data_dir=tmp_path / "data",
    )
    assert report.status == "completed"
    with pytest.raises(RuntimeError, match="not paused"):
        resume_task(report.run_id, data_dir=tmp_path / "data")


def test_resume_non_clarification_payload_rejected_when_pending(tmp_path: Path) -> None:
    """澄清挂起时用 ResumePayload 恢复必须拒绝（004 十三）。"""
    from app.core.schemas import ClarificationPayload
    from app.runner import resume_task, run_task

    report = run_task("vague_goal", token_budget=10000, cost_budget=1.0, data_dir=tmp_path / "data")
    assert report.status == "paused"
    with pytest.raises(RuntimeError, match="awaiting clarification"):
        resume_task(
            report.run_id, payload=ResumePayload(action="continue"), data_dir=tmp_path / "data"
        )
    # clarification_id 不匹配同样拒绝
    with pytest.raises(RuntimeError, match="clarification_id mismatch"):
        resume_task(
            report.run_id,
            payload=ClarificationPayload(clarification_id="cl-wrong", answer="x"),
            data_dir=tmp_path / "data",
        )


def test_empty_clarification_rejected() -> None:
    """空澄清答案被 Schema 拒绝（004 十三）。"""
    from pydantic import ValidationError

    from app.core.schemas import ClarificationPayload

    with pytest.raises(ValidationError):
        ClarificationPayload(clarification_id="cl-1", answer="")
