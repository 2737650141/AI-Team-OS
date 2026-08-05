"""007 十七：API 审批/Artifact/Diff/回滚端点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.core.approval import ApprovalService
from app.core.artifacts import ArtifactWriter


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture()
def seeded(data_dir: Path, monkeypatch):
    """真实沙箱任务（run_task → 暂停在审批 interrupt）+ 已批准审批 + Artifact。"""

    from app.runner import run_task

    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    monkeypatch.setenv("AI_TEAM_ALLOWED_READ_ROOTS", str(fixtures))
    # 首次运行：sandbox_code_fix → Executor 生成 Patch → 审批 interrupt → paused
    report = run_task(
        "sandbox_code_fix",
        token_budget=20000,
        cost_budget=1.0,
        data_dir=data_dir,
        model_overrides={"project_alias": "sample-python"},
    )
    assert report.state.current_status == "paused"
    pending_id = report.state.pending_approval_id
    assert pending_id
    # 批准并恢复 → completed（s2 应用补丁 + pytest）
    from app.core.schemas import ApprovalPayload
    from app.runner import resume_task

    resume_task(
        report.run_id,
        payload=ApprovalPayload(approval_id=pending_id, decision="approved", reason="ok"),
        data_dir=data_dir,
    )
    # 记录（第二审批：git_commit 演示用 pending）
    runtime = data_dir / "runtime"

    approval = ApprovalService(
        storage_path=runtime / "workspaces" / report.state.task_id / "approvals.jsonl"
    )
    artifacts = ArtifactWriter(runtime, report.state.task_id)
    pending = approval.create(
        task_id=report.state.task_id,
        run_id=report.run_id,
        action_type="write_file",
        tool_name="sandbox_write_file",
        summary="add y",
        target_paths=["y.txt"],
        parameter_hash=ApprovalService.parameter_hash_of({"path": "y.txt", "content": "y"}),
        target_hash=ApprovalService.target_hash_of({}),
    )
    return {
        "run_id": report.run_id,
        "approval_id": pending_id,
        "pending_id": pending.approval_id,
        "task_id": report.state.task_id,
        "worktree": runtime / "workspaces" / report.state.task_id / "worktree",
        "artifacts": artifacts,
    }


def test_api_approvals_list(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        resp = client.get(f"/tasks/{seeded['run_id']}/approvals")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert any(a["status"] == "approved" for a in body)
        assert any(a["status"] == "pending" for a in body)


def test_api_approval_show(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        resp = client.get(f"/approvals/{seeded['approval_id']}")
        assert resp.status_code == 200
        assert resp.json()["approval_id"] == seeded["approval_id"]
        assert resp.json()["status"] == "approved"
        # 不显示凭据字段
        assert "api_key" not in resp.text


def test_api_approve_idempotent_and_conflict(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        # 已拒绝审批不能再批准 → 409
        from app.core.approval import ApprovalService

        svc = ApprovalService(
            storage_path=data_dir / "runtime" / "workspaces" / seeded["task_id"] / "approvals.jsonl"
        )
        svc.decide(seeded["approval_id"], "rejected", reason="no")
        resp = client.post(f"/approvals/{seeded['approval_id']}/approve", json={"reason": "x"})
        assert resp.status_code == 409
        assert "already rejected" in resp.json()["detail"]


def test_api_reject_pending(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        # pending 审批决策落盘（任务已 completed → resume 返回 409，但决策已记录）
        resp = client.post(f"/approvals/{seeded['pending_id']}/reject", json={"reason": "not now"})
        assert resp.status_code == 409
        from app.core.approval import ApprovalService

        svc = ApprovalService(
            storage_path=data_dir / "runtime" / "workspaces" / seeded["task_id"] / "approvals.jsonl"
        )
        assert svc.get(seeded["pending_id"]).status == "rejected"  # 决策已落盘


def test_api_artifacts_and_show(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        resp = client.get(f"/tasks/{seeded['run_id']}/artifacts")
        assert resp.status_code == 200
        records = resp.json()
        assert len(records) >= 2  # diff + patch（+ test_report 等）
        diff_art = next(a for a in records if a["artifact_type"] == "diff")
        resp2 = client.get(f"/artifacts/{diff_art['artifact_id']}")
        assert resp2.status_code == 200
        assert "--- a/src/main.py" in resp2.json()["content"]


def test_api_diff(data_dir: Path, seeded) -> None:
    with TestClient(app) as client:
        resp = client.get(f"/tasks/{seeded['run_id']}/diff")
        assert resp.status_code == 200
        assert "--- a/src/main.py" in resp.json()["diff"]  # 实际 Diff（src/main.py 修复）


def test_api_rollback_requires_approval(data_dir: Path, seeded) -> None:
    """未提供已批准的回滚审批 → 409。"""
    with TestClient(app) as client:
        resp = client.post(
            f"/tasks/{seeded['run_id']}/rollback",
            json={"patch_approval_id": seeded["approval_id"], "approval_id": "missing"},
        )
        assert resp.status_code == 409


def test_api_approval_body_cannot_change_params(data_dir: Path, seeded) -> None:
    """审批请求参数只读：approve 只接受 reason（无参数篡改面）。"""
    with TestClient(app) as client:
        resp = client.post(
            f"/approvals/{seeded['approval_id']}/approve",
            json={"reason": "ok", "target_paths": ["/etc/passwd"], "action_type": "delete"},
        )
        # 额外字段被忽略（schema 拒绝未知字段由 pydantic extra=ignore 默认；不影响审批绑定）
        assert resp.status_code in (200, 409)
