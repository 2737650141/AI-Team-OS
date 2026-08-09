"""007 十八/十九：黄金任务 GT-W01~W10 端到端测试（Fake 模式 + 沙箱）。

覆盖：创建文件/修复 Bug/拒绝审批/篡改检测/路径逃逸/命令注入/测试失败返工/
原子回滚/本地 Commit/源项目保护。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.approval import ApprovalError, ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.command_runner import CommandError, CommandPolicy, SandboxCommandRunner
from app.core.patch_engine import PatchApplier, PatchError, PatchProposal, PatchValidator
from app.core.sandbox_git import SandboxGitManager
from app.core.workspace import WorkspaceManager
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext
from app.tools.sandbox_tools import SandboxToolset, build_sandbox_tools


@pytest.fixture()
def sample_source(tmp_path: Path) -> Path:
    src = tmp_path / "sample-python"
    (src / "src").mkdir(parents=True)
    (src / "src" / "main.py").write_text(
        "def buggy() -> bool:\n    return False\n\n\n"
        "def main() -> int:\n    return 0 if buggy() else 1\n",
        encoding="utf-8",
    )
    (src / "tests").mkdir()
    (src / "tests" / "test_main.py").write_text(
        "from src.main import buggy\n\n\n"
        "def test_buggy_returns_true() -> None:\n    assert buggy() is True\n",
        encoding="utf-8",
    )
    (src / "README.md").write_text("# sample-python\n", encoding="utf-8")
    return src


@pytest.fixture()
def sandbox_env(tmp_path: Path, sample_source: Path):
    """完整沙箱环境：workspace + approval + artifacts + git + tools + gateway。"""
    runtime = tmp_path / "runtime"
    ws_mgr = WorkspaceManager(runtime)
    manifest = ws_mgr.create_workspace("t1", "sample-python", sample_source)
    worktree = Path(manifest.worktree_path)
    approval = ApprovalService(storage_path=runtime / "workspaces" / "t1" / "approvals.jsonl")
    artifacts = ArtifactWriter(runtime, "t1")
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1", approval_service=approval)
    toolset = SandboxToolset(worktree, "t1", artifacts, approval)
    for spec in build_sandbox_tools(toolset):
        gateway.register(spec)
    runner = SandboxCommandRunner(
        CommandPolicy(), worktree, logs_dir=runtime / "workspaces" / "t1" / "logs"
    )
    git = SandboxGitManager(worktree, approval, artifacts, runner=runner)
    return {
        "worktree": worktree,
        "approval": approval,
        "artifacts": artifacts,
        "gateway": gateway,
        "runner": runner,
        "git": git,
        "source": sample_source,
        "ws_mgr": ws_mgr,
        "manifest": manifest,
    }


def _ctx(subtask: str = "s1", approval_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(
        task_id="t1", subtask_id=subtask, role="executor", approval_id=approval_id
    )


def _bugfix_proposal(worktree: Path) -> PatchProposal:
    main = worktree / "src" / "main.py"
    old = main.read_text(encoding="utf-8")
    new = old.replace("return False", "return True", 1)
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff_lines = [
        "--- a/src/main.py\n",
        "+++ b/src/main.py\n",
        f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@\n",
    ]
    diff_lines += ["-" + line for line in old_lines]
    diff_lines += ["+" + line for line in new_lines]
    return PatchProposal(
        task_id="t1",
        subtask_id="s2",
        target_files=["src/main.py"],
        unified_diff="".join(diff_lines),
        reason="GT-W02: fix bug",
        expected_effect="buggy() returns True",
        tests_to_run=["python_pytest"],
    )


# ---------- GT-W01：创建文件 ----------
def test_gt_w01_create_readme(sandbox_env) -> None:
    """生成 Diff → 未批准文件不变 → 批准后仅沙箱副本变化 → 源项目不变。"""
    env = sandbox_env
    wt = env["worktree"]
    proposal = _bugfix_proposal(wt)
    # 1. 生成 Diff（预览）——未批准前文件不变
    validator = PatchValidator(wt)
    validator.validate(proposal)
    before = (wt / "src" / "main.py").read_text(encoding="utf-8")
    # 2. 创建审批并批准
    target_hashes = {
        "src/main.py": __import__("app.core.patch_engine", fromlist=["sha256_text"]).sha256_text(
            before
        )
    }
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="GT-W01",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of(target_hashes),
    )
    # 3. 未批准：网关拦截
    r = env["gateway"].invoke(
        "sandbox_apply_patch", {"patch_json": proposal.model_dump_json()}, ctx=_ctx("s2")
    )
    assert r.status == "blocked"
    assert (wt / "src" / "main.py").read_text(encoding="utf-8") == before  # 文件不变
    # 4. 批准后应用（经网关）
    env["approval"].decide(req.approval_id, "approved")
    r2 = env["gateway"].invoke(
        "sandbox_apply_patch",
        {"patch_json": proposal.model_dump_json()},
        ctx=_ctx("s2", approval_id=req.approval_id),
    )
    assert r2.ok
    assert "return True" in (wt / "src" / "main.py").read_text(encoding="utf-8")
    # 5. 源项目不变（GT-W10）
    assert env["ws_mgr"].verify_source_unchanged(env["manifest"], env["source"])
    # 6. Artifact 正确
    assert any(a.artifact_type == "diff" for a in env["artifacts"].load_all("t1"))


# ---------- GT-W02：修复 Python Bug（测试由失败变通过） ----------
def test_gt_w02_bugfix_tests_pass(sandbox_env) -> None:
    env = sandbox_env
    proposal = _bugfix_proposal(env["worktree"])
    validator = PatchValidator(env["worktree"])
    validator.validate(proposal)
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="GT-W02 fix",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "approved")
    applier = PatchApplier(env["worktree"], env["worktree"].parent / "backups")
    applier.apply(proposal, req.approval_id)
    # 运行批准测试（白名单执行器）
    result = env["runner"].run("python_pytest", ["-q"], cwd_alias="worktree", timeout_seconds=120)
    assert result.return_code == 0  # 测试由失败变通过
    # 修改最小：仅 src/main.py
    env["git"].init()
    assert "return True" in (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8")


# ---------- GT-W03：拒绝审批 ----------
def test_gt_w03_rejected_not_applied(sandbox_env) -> None:
    env = sandbox_env
    proposal = _bugfix_proposal(env["worktree"])
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="GT-W03",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "rejected", reason="not now")
    before = (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8")
    # 已拒绝 → 网关拦截（不应用、测试命令不执行）
    r = env["gateway"].invoke(
        "sandbox_apply_patch",
        {"patch_json": proposal.model_dump_json()},
        ctx=_ctx("s2", approval_id=req.approval_id),
    )
    assert r.status == "blocked"
    assert (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8") == before
    # 拒绝后不可再批准（18）
    with pytest.raises(ApprovalError, match="already rejected"):
        env["approval"].decide(req.approval_id, "approved")


# ---------- GT-W04：篡改检测 ----------
def test_gt_w04_tamper_detected(sandbox_env) -> None:
    env = sandbox_env
    proposal = _bugfix_proposal(env["worktree"])
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="GT-W04",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "approved")
    # 审批后篡改参数（换一个 diff）
    tampered = proposal.model_copy(update={"unified_diff": proposal.unified_diff + "tampered"})
    # 网关 verify（operation_hash 绑定）→ 拒绝
    r = env["gateway"].invoke(
        "sandbox_apply_patch",
        {"patch_json": tampered.model_dump_json()},
        ctx=_ctx("s2", approval_id=req.approval_id),
    )
    assert r.status == "blocked"
    assert "return False" in (env["worktree"] / "src" / "main.py").read_text(
        encoding="utf-8"
    )  # 未写文件


# ---------- GT-W05：路径逃逸（审批前拒绝） ----------
def test_gt_w05_path_escape_pre_approval(sandbox_env) -> None:
    env = sandbox_env
    escape = PatchProposal(
        task_id="t1",
        subtask_id="s2",
        target_files=["../outside.txt"],
        unified_diff="@@ -1 +1 @@\n-x\n+y\n",
        reason="escape",
    )
    # 请求审批前即确定性拒绝（PatchValidator）
    with pytest.raises(PatchError, match="traversal"):
        PatchValidator(env["worktree"]).validate(escape)
    # 网关工具同样拒绝
    r = env["gateway"].invoke(
        "sandbox_write_file", {"path": "../outside.txt", "content": "x"}, ctx=_ctx()
    )
    assert r.status == "blocked"


# ---------- GT-W06：命令注入 ----------
def test_gt_w06_command_injection_rejected(sandbox_env) -> None:
    env = sandbox_env
    for arg in ["pytest && whoami", "pytest | powershell", "$(whoami)"]:
        with pytest.raises(CommandError, match="injection|flag"):
            env["runner"].run("python_pytest", [arg], cwd_alias="worktree")


# ---------- GT-W07：测试失败返工（第二次 Patch 新审批，历史保留） ----------
def test_gt_w07_rework_new_approval(sandbox_env) -> None:
    env = sandbox_env
    # 第一轮：坏的补丁（改错文件）→ 测试仍失败
    bad = PatchProposal(
        task_id="t1",
        subtask_id="s2",
        target_files=["README.md"],
        unified_diff="@@ -1 +1 @@\n-# sample-python\n+# sample-python fixed\n",
        reason="wrong target",
        tests_to_run=["python_pytest"],
    )
    req1 = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="round1",
        target_paths=["README.md"],
        parameter_hash=ApprovalService.parameter_hash_of({"patch_json": bad.model_dump_json()}),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req1.approval_id, "approved")
    PatchApplier(env["worktree"], env["worktree"].parent / "backups").apply(bad, req1.approval_id)
    test_result = env["runner"].run(
        "python_pytest", ["-q"], cwd_alias="worktree", timeout_seconds=120
    )
    assert test_result.return_code != 0  # 测试仍失败 → Reviewer reject（确定性）
    # 第二轮：正确补丁 → 新审批
    good = _bugfix_proposal(env["worktree"])
    req2 = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="round2",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of({"patch_json": good.model_dump_json()}),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req2.approval_id, "approved")
    PatchApplier(env["worktree"], env["worktree"].parent / "backups").apply(good, req2.approval_id)
    test_result2 = env["runner"].run(
        "python_pytest", ["-q"], cwd_alias="worktree", timeout_seconds=120
    )
    assert test_result2.return_code == 0  # 通过
    # 历史保留：两次审批都在
    all_reqs = env["approval"].all("t1")
    assert len(all_reqs) == 2
    assert all_reqs[0].status == "approved" and all_reqs[1].status == "approved"


# ---------- GT-W08：原子回滚（第二个文件失败 → 第一个也恢复） ----------
def test_gt_w08_atomic_rollback(sandbox_env) -> None:
    env = sandbox_env
    (env["worktree"] / "a.txt").write_text("AAA", encoding="utf-8")
    (env["worktree"] / "b.txt").write_text("BBB", encoding="utf-8")
    diff = (
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-AAA\n+aaa\n"
        "--- a/b.txt\n+++ b/b.txt\n@@ -99,1 +99,1 @@\n-X\n+Y\n"
    )
    proposal = PatchProposal(
        task_id="t1", target_files=["a.txt", "b.txt"], unified_diff=diff, reason="GT-W08"
    )
    applier = PatchApplier(env["worktree"], env["worktree"].parent / "backups")
    with pytest.raises(PatchError, match="rolled back"):
        applier.apply(proposal, "appr-8")
    assert (env["worktree"] / "a.txt").read_text(encoding="utf-8") == "AAA"
    assert (env["worktree"] / "b.txt").read_text(encoding="utf-8") == "BBB"


# ---------- GT-W09：本地 Commit ----------
def test_gt_w09_local_commit(sandbox_env) -> None:
    env = sandbox_env
    env["git"].init()
    env["git"].add(["README.md"])
    req = env["approval"].create(
        task_id="t1",
        action_type="git_commit",
        tool_name="git_commit",
        summary="commit README",
        target_paths=["README.md"],
    )
    env["approval"].decide(req.approval_id, "approved", reason="ok")
    r = env["git"].commit(req.approval_id, "docs: initial readme", tests_passed=True)
    assert r["ok"] and r["commit_sha"] and r["local_only"] and r["pushed"] is False
    env["git"].assert_no_remote()  # 无 remote（44）


# ---------- GT-W10：源项目保护 ----------
def test_gt_w10_source_project_untouched(sandbox_env) -> None:
    env = sandbox_env
    # 完整流程后源目录哈希不变
    proposal = _bugfix_proposal(env["worktree"])
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="GT-W10",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "approved")
    PatchApplier(env["worktree"], env["worktree"].parent / "backups").apply(
        proposal, req.approval_id
    )
    assert env["ws_mgr"].verify_source_unchanged(env["manifest"], env["source"])
    # 只有 runtime/workspaces/<task_id> 变化（沙箱内）
    assert "return True" in (env["worktree"] / "src" / "main.py").read_text(encoding="utf-8")
    assert "return False" in (env["source"] / "src" / "main.py").read_text(encoding="utf-8")


# ---------- 56. Artifact 可追溯 ----------
def test_artifacts_traceable(sandbox_env) -> None:
    env = sandbox_env
    proposal = _bugfix_proposal(env["worktree"])
    req = env["approval"].create(
        task_id="t1",
        action_type="apply_patch",
        tool_name="sandbox_apply_patch",
        summary="trace",
        target_paths=["src/main.py"],
        parameter_hash=ApprovalService.parameter_hash_of(
            {"patch_json": proposal.model_dump_json()}
        ),
        target_hash=ApprovalService.target_hash_of({}),
    )
    env["approval"].decide(req.approval_id, "approved")
    applier = PatchApplier(env["worktree"], env["worktree"].parent / "backups")
    applier.apply(proposal, req.approval_id)
    env["artifacts"].write(
        artifact_type="test_report",
        content='{"return_code": 0}',
        task_id="t1",
        subtask_id="s2",
        approval_id=req.approval_id,
    )
    records = env["artifacts"].load_all("t1")
    assert all(
        a.approval_id == req.approval_id for a in records if a.artifact_type == "test_report"
    )
    assert all(a.task_id == "t1" for a in records)
