"""007 十九：Git 闭环测试（44-51）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.approval import ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.command_runner import CommandError, CommandPolicy, SandboxCommandRunner
from app.core.sandbox_git import SandboxGitError, SandboxGitManager


@pytest.fixture()
def git_env(tmp_path: Path):
    worktree = tmp_path / "runtime" / "workspaces" / "t1" / "worktree"
    worktree.mkdir(parents=True)
    (worktree / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    approval = ApprovalService()
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    policy = CommandPolicy()
    runner = SandboxCommandRunner(policy, worktree)
    mgr = SandboxGitManager(worktree, approval, artifacts, policy=policy, runner=runner)
    return worktree, mgr, approval, artifacts


# ---------- 44. 无 remote ----------
def test_no_remote(git_env) -> None:
    _, mgr, _, _ = git_env
    mgr.init()
    mgr.assert_no_remote()  # 不抛


# ---------- 45. hooks 禁用 ----------
def test_hooks_disabled(git_env) -> None:
    worktree, mgr, _, _ = git_env
    mgr.init()
    hooks = worktree.parent / "hooks"
    assert hooks.is_dir()
    # 验证 core.hooksPath 指向空目录（hooks 不执行）
    assert not any(hooks.iterdir())


# ---------- 46. status ----------
def test_git_status(git_env) -> None:
    _, mgr, _, _ = git_env
    mgr.init()
    r = mgr.status()
    assert r["return_code"] == 0
    assert "main.py" in r["stdout"]  # 未跟踪文件


# ---------- 47. diff ----------
def test_git_diff(git_env) -> None:
    worktree, mgr, _, _ = git_env
    mgr.init()
    (worktree / "main.py").write_text("changed", encoding="utf-8")
    r = mgr.diff()
    assert r["return_code"] == 0


# ---------- 48. add 指定路径 ----------
def test_git_add_paths(git_env) -> None:
    worktree, mgr, _, _ = git_env
    mgr.init()
    r = mgr.add(["main.py"])
    assert r["return_code"] == 0
    with pytest.raises(SandboxGitError, match="invalid add paths"):
        mgr.add(["/etc/passwd"])


# ---------- 49. 本地 commit（approval 绑定 + Commit Artifact） ----------
def test_git_commit(git_env) -> None:
    worktree, mgr, approval, artifacts = git_env
    mgr.init()
    mgr.add(["main.py"])
    req = approval.create(
        task_id="t1",
        action_type="git_commit",
        tool_name="sandbox_git_commit",
        summary="commit main.py",
        target_paths=["main.py"],
    )
    approval.decide(req.approval_id, "approved", reason="ok")
    r = mgr.commit(req.approval_id, "fix: main", tests_passed=True)
    assert r["ok"] and r["local_only"] and r["pushed"] is False
    assert r["commit_sha"]
    # Commit Artifact 记录
    records = artifacts.load_all("t1")
    assert any(a.artifact_type == "git_commit" for a in records)
    assert "pushed" in records[-1].metadata or "pushed" in artifacts.read_content(records[-1])


# ---------- 50. push 不可达 ----------
def test_push_unreachable(git_env) -> None:
    _, mgr, _, _ = git_env
    mgr.init()
    with pytest.raises(CommandError, match="not allowed"):
        mgr._runner.run("git_push", [], cwd_alias="worktree")


# ---------- 51. 不修改全局配置 ----------
def test_global_config_untouched(git_env) -> None:
    """所有 git 配置均 --local 作用域（沙箱仓库内），不写全局。"""
    worktree, mgr, _, _ = git_env
    mgr.init()
    # git config --global 不可达（无对应白名单）
    with pytest.raises(CommandError):
        mgr._runner.run("git_config_global", [], cwd_alias="worktree")


# ---------- 52 前置：commit 需要批准 ----------
def test_commit_without_approval_rejected(git_env) -> None:
    _, mgr, approval, _ = git_env
    mgr.init()
    req = approval.create(
        task_id="t1",
        action_type="git_commit",
        tool_name="git_commit",
        summary="no approval yet",
        target_paths=["main.py"],
    )  # 未批准
    with pytest.raises(SandboxGitError, match="approval not approved"):
        mgr.commit(req.approval_id, "should not commit")
