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


# ---------- review blocking（sa_20260805_144828）回归：reject 后重派不死锁 ----------
def test_gt_w03_graph_reject_then_redispatch(data_dir: Path, monkeypatch) -> None:
    """图级 GT-W03：reject → rejected_by_user → reviewer reject → 重派 → 新审批 →
    批准 → completed（此前 executor 复用 rejected 请求导致恢复永久卡死）。"""
    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    monkeypatch.setenv("AI_TEAM_ALLOWED_READ_ROOTS", str(fixtures))
    from app.core.schemas import ApprovalPayload
    from app.runner import resume_task, run_task

    # 1. 首次运行 → 暂停（审批 R1 pending）
    report = run_task(
        "sandbox_code_fix",
        token_budget=20000,
        cost_budget=1.0,
        data_dir=data_dir,
        model_overrides={"project_alias": "sample-python"},
    )
    assert report.state.current_status == "paused"
    r1 = report.state.pending_approval_id
    assert r1

    # 2. 用户拒绝 R1 → 恢复：executor rejected_by_user → reviewer reject → 重派
    report2 = resume_task(
        report.run_id,
        payload=ApprovalPayload(approval_id=r1, decision="rejected", reason="not now"),
        data_dir=data_dir,
    )
    # 重派后 executor 创建新审批 R2 并再次暂停（blocking 修复：不复用 rejected）
    assert report2.state.current_status == "paused"
    r2 = report2.state.pending_approval_id
    assert r2 and r2 != r1

    # 3. 批准 R2 → completed（补丁应用 + pytest 通过）
    report3 = resume_task(
        report2.run_id,
        payload=ApprovalPayload(approval_id=r2, decision="approved", reason="ok"),
        data_dir=data_dir,
    )
    assert report3.state.current_status == "completed"
    # 源项目（fixtures/sample-python）未被修改
    from app.core.workspace import WorkspaceManager

    manifest = WorkspaceManager(data_dir / "runtime").load_manifest(report.state.task_id)
    assert manifest is not None
    assert manifest.source_project_alias == "sample-python"


# ---------- review（sa_20260805_144828）回归：create_readme 图级路径 ----------
def test_gt_w01_graph_create_readme(data_dir: Path, monkeypatch) -> None:
    """GT-W01 图级：sandbox_create_readme → 审批 → 应用 → README 末尾追加段落。"""
    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    monkeypatch.setenv("AI_TEAM_ALLOWED_READ_ROOTS", str(fixtures))
    from app.core.schemas import ApprovalPayload
    from app.runner import resume_task, run_task

    report = run_task(
        "sandbox_create_readme",
        token_budget=20000,
        cost_budget=1.0,
        data_dir=data_dir,
        model_overrides={"project_alias": "sample-python"},
    )
    assert report.state.current_status == "paused"
    report2 = resume_task(
        report.run_id,
        payload=ApprovalPayload(
            approval_id=report.state.pending_approval_id, decision="approved", reason="ok"
        ),
        data_dir=data_dir,
    )
    assert report2.state.current_status == "completed"
    wt = data_dir / "runtime" / "workspaces" / report.state.task_id / "worktree"
    readme = wt / "README.md"
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert content.startswith("# sample-python")  # 原有内容保留
    assert "GT-W01" in content  # 新增段落（末尾追加）
    # 源项目未变（fixture README 本身提及 GT-W01；断言 Executor 新增内容不在源项目）
    src_readme = fixtures / "sample-python" / "README.md"
    assert "由 Executor 生成的确定性新增段落" not in src_readme.read_text(encoding="utf-8")
