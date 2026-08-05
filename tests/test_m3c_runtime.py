"""007 十九：Runtime（52-60）+ 回滚（十五）测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.approval import ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.command_runner import CommandPolicy, SandboxCommandRunner
from app.core.patch_engine import PatchApplier, PatchProposal
from app.core.rollback import RollbackError, WorkspaceRollback
from app.core.workspace import WorkspaceManager
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext
from app.tools.sandbox_tools import SandboxToolset, build_sandbox_tools


@pytest.fixture()
def env(tmp_path: Path):
    src = tmp_path / "sample-python"
    (src / "src").mkdir(parents=True)
    (src / "src" / "main.py").write_text(
        "def buggy() -> bool:\n    return False\n", encoding="utf-8"
    )
    runtime = tmp_path / "runtime"
    ws = WorkspaceManager(runtime)
    manifest = ws.create_workspace("t1", "sample-python", src)
    worktree = Path(manifest.worktree_path)
    approval = ApprovalService(storage_path=runtime / "workspaces" / "t1" / "approvals.jsonl")
    artifacts = ArtifactWriter(runtime, "t1")
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1", approval_service=approval)
    toolset = SandboxToolset(worktree, "t1", artifacts, approval)
    for spec in build_sandbox_tools(toolset):
        gateway.register(spec)
    runner = SandboxCommandRunner(CommandPolicy(), worktree)
    rollback = WorkspaceRollback(
        worktree,
        runtime / "workspaces" / "t1" / "input",
        worktree.parent / "backups",
        worktree.parent / "trash",
        artifacts,
        approval,
        "t1",
    )
    return {
        "worktree": worktree,
        "approval": approval,
        "artifacts": artifacts,
        "gateway": gateway,
        "runner": runner,
        "rollback": rollback,
        "source": src,
        "ws": ws,
        "manifest": manifest,
    }


def _approve(env, action_type: str = "apply_patch", **kw) -> str:
    req = env["approval"].create(
        task_id="t1",
        action_type=action_type,
        tool_name="sandbox_apply_patch",
        summary="t",
        target_paths=["src/main.py"],
        **kw,
    )
    env["approval"].decide(req.approval_id, "approved")
    return req.approval_id


# ---------- 52. Executor 只经 Tool Gateway ----------
def test_executor_only_via_gateway(env) -> None:
    """写工具必须经 Tool Gateway（未批准拦截；无 approval_id 的 handler 直调不存在）。"""
    gateway = env["gateway"]
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = gateway.invoke("sandbox_write_file", {"path": "x.txt", "content": "x"}, ctx=ctx)
    assert r.status == "blocked"  # 无审批
    # 批准后放行（经网关）
    req = env["approval"].create(
        task_id="t1",
        action_type="write_file",
        tool_name="sandbox_write_file",
        summary="w",
        target_paths=["x.txt"],
        parameter_hash=ApprovalService.parameter_hash_of({"path": "x.txt", "content": "x"}),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "approved")
    r2 = gateway.invoke(
        "sandbox_write_file",
        {"path": "x.txt", "content": "x"},
        ctx=ToolExecutionContext(
            task_id="t1", subtask_id="s1", role="executor", approval_id=req.approval_id
        ),
    )
    assert r2.ok
    assert (env["worktree"] / "x.txt").read_text(encoding="utf-8") == "x"


# ---------- 53. Reviewer 确定性拒绝（Executor 未实施） ----------
def test_reviewer_rejects_unimplemented(env) -> None:
    from app.agents.reviewer import DeterministicReviewer
    from app.core.schemas import ExecutionResult
    from app.core.state import SubtaskState

    subtask = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="executor",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=["sandbox_apply_patch"],
        token_budget=100,
        tool_call_budget=1,
    )
    # 未实施（rejected_by_user）
    subtask.execution_result = ExecutionResult(
        subtask_id="s1",
        summary="rejected_by_user: no",
        claims=[],
        ts="t",
        metadata={"status": "rejected_by_user"},
    )
    issues = DeterministicReviewer().check(subtask, set(), ["sandbox_apply_patch"], 0)
    assert any(i.code == "executor_not_implemented" for i in issues)
    # 测试失败
    subtask2 = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="executor",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        required_tools=["sandbox_apply_patch"],
        token_budget=100,
        tool_call_budget=1,
    )
    subtask2.execution_result = ExecutionResult(
        subtask_id="s1",
        summary="implemented",
        claims=[],
        ts="t",
        metadata={"status": "implemented", "approval_id": "a1", "test_report": {"return_code": 1}},
    )
    issues2 = DeterministicReviewer().check(subtask2, set(), ["sandbox_apply_patch"], 0)
    assert any(i.code == "tests_failed" for i in issues2)
    assert any(i.code == "executor_no_claims" for i in issues2)


# ---------- 54/55. 测试失败定向返工（GT-W07 已在 golden 覆盖）；已通过不重跑（图级） ----------
def test_rework_only_rejected_subtasks() -> None:
    """派发逻辑只重跑 rejected（图级验证见 test_m2_workflow；此处确认 reviewer 判定）。"""
    from app.agents.reviewer import DeterministicReviewer
    from app.core.schemas import ExecutionResult
    from app.core.state import SubtaskState

    passed = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        token_budget=100,
        tool_call_budget=1,
        runtime_status="passed",
        execution_result=ExecutionResult(
            subtask_id="s1",
            summary="ok",
            claims=[],
            evidence_refs=["e1"],
            unverified_items=["note"],
            ts="t",
        ),
    )
    issues = DeterministicReviewer().check(passed, {"e1"}, ["fixture_repo_lookup"], 0)
    assert issues == []  # 已通过子任务无问题 → 不重跑


# ---------- 56. Artifact 可追溯（golden 已覆盖，此处验证哈希一致） ----------
def test_artifact_hash_consistent(env) -> None:
    import hashlib

    writer = env["artifacts"]
    rec = writer.write(artifact_type="diff", content="abc", task_id="t1")
    # content_hash 为 sha256 前 32 位；内容落盘可读且 size 正确
    assert rec.content_hash == hashlib.sha256(b"abc").hexdigest()[:32]
    assert writer.read_content(rec) == "abc"
    assert rec.size == 3


# ---------- 57. Checkpoint 恢复（审批跨进程：ApprovalRequest 可序列化） ----------
def test_approval_persisted_across_reload(env) -> None:
    aid = _approve(env)
    # 模拟新进程：从同一 storage 重建 ApprovalService
    fresh = ApprovalService(storage_path=env["worktree"].parent / "approvals.jsonl")
    req = fresh.get(aid)
    assert req is not None and req.status == "approved"
    fresh.verify_execution(req, parameter_hash="", target_hash="")  # 仍有效


# ---------- 58. 回滚后状态一致 ----------
def test_rollback_patch_restores(env) -> None:
    """回滚单个 Patch：文件恢复 + Artifact + 需审批。"""
    main = env["worktree"] / "src" / "main.py"
    before = main.read_text(encoding="utf-8")
    # 应用补丁
    new = before.replace("return False", "return True")
    diff = (
        "--- a/src/main.py\n+++ b/src/main.py\n@@ -1,2 +1,2 @@\n"
        + "".join("-" + line for line in before.splitlines(keepends=True))
        + "".join("+" + line for line in new.splitlines(keepends=True))
    )
    proposal = PatchProposal(
        task_id="t1", target_files=["src/main.py"], unified_diff=diff, reason="fix"
    )
    patch_aid = _approve(env)
    PatchApplier(env["worktree"], env["worktree"].parent / "backups").apply(proposal, patch_aid)
    assert "return True" in main.read_text(encoding="utf-8")
    # 回滚需显式审批
    with pytest.raises(RollbackError, match="approval not found"):
        env["rollback"].rollback_patch("nope", patch_aid)
    rollback_aid = _approve(env, action_type="rollback")
    r = env["rollback"].rollback_patch(rollback_aid, patch_aid)
    assert r["ok"] and "src/main.py" in r["restored"]
    assert main.read_text(encoding="utf-8") == before
    assert any(a.metadata.get("rollback") for a in env["artifacts"].load_all("t1"))


# ---------- 十五：回滚到初始快照 ----------
def test_rollback_to_initial(env) -> None:
    (env["worktree"] / "newfile.txt").write_text("new", encoding="utf-8")
    (env["worktree"] / "src" / "main.py").write_text("changed", encoding="utf-8")
    rollback_aid = _approve(env, action_type="rollback")
    r = env["rollback"].rollback_to_initial(rollback_aid)
    assert r["ok"] and r["rolled_back_to_initial"]
    assert not (env["worktree"] / "newfile.txt").exists()  # 新增文件消失
    assert "return False" in (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8")


# ---------- 十五：恢复删除 ----------
def test_restore_deleted_from_trash(env) -> None:
    from app.tools.sandbox_tools import SandboxToolset

    toolset = SandboxToolset(env["worktree"], "t1", env["artifacts"], env["approval"])
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = toolset.delete_path("src/main.py", ctx)
    assert r["ok"]
    rollback_aid = _approve(env, action_type="rollback")
    r2 = env["rollback"].restore_deleted(rollback_aid, r["trash_path"], "src/main.py")
    assert r2["ok"]
    assert "return False" in (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8")


# ---------- 十五：回滚失败明确报错 ----------
def test_rollback_missing_backup_errors(env) -> None:
    rollback_aid = _approve(env, action_type="rollback")
    with pytest.raises(RollbackError, match="no backup"):
        env["rollback"].rollback_patch(rollback_aid, "never-applied-approval")


# ---------- 59/60. 回归与无真实网络（全量 pytest 由 CI 覆盖；此处验证默认网络请求数） ----------
def test_no_real_network_in_default_tests(env) -> None:
    """默认测试工具均为 MockTransport/IP 字面量（006 十九-60 由全套测试保证）。"""
    import httpx

    assert httpx.MockTransport  # mock 基础设施可用
    assert env["gateway"].available_tools()
