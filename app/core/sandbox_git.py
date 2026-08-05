"""本地 Git 闭环（007 十一）：SandboxGitManager。

- 沙箱 worktree 独立 Git 仓库：git init（无 remote、无 credential 继承）。
- 不修改全局 Git 配置（--local 作用域）；hooks 通过 core.hooksPath 指向空目录禁用（11.4）。
- 允许：status/diff/diff-check/log/add 指定路径/本地 commit（11.2）。
- 禁止：remote/fetch/pull/push/clone/submodule/credential/force（11.3）。
- 本地 commit 需要 explicit approval（11.5）；Commit Artifact 记录
  commit_sha/message/changed_files/diff_hash/approval_id/tests_passed。
- 不得将"本地 commit"表述为"已发布/已提交到远程"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.approval import ApprovalError, ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.command_runner import CommandPolicy, SandboxCommandRunner

FORBIDDEN_GIT_IDS = {
    "git_remote",
    "git_fetch",
    "git_pull",
    "git_push",
    "git_clone",
    "git_submodule",
    "git_credential",
}
FORBIDDEN_GIT_FLAGS = (
    "--force",
    "-f",
    "--mirror",
    "--all",
    "--tags",
    "--prune",
    "--set-upstream",
    "--bare",
)


class SandboxGitError(Exception):
    """沙箱 Git 错误（安全消息）。"""


class SandboxGitManager:
    """沙箱 Git 管理（11.1-11.5）。"""

    def __init__(
        self,
        worktree: Path,
        approval: ApprovalService,
        artifacts: ArtifactWriter,
        policy: CommandPolicy | None = None,
        runner: SandboxCommandRunner | None = None,
        identity_name: str = "AI Team OS Sandbox",
        identity_email: str = "sandbox@local",
    ) -> None:
        self._worktree = worktree
        self._approval = approval
        self._artifacts = artifacts
        self._runner = runner or SandboxCommandRunner(policy or CommandPolicy(), worktree)
        self._identity = (identity_name, identity_email)

    # ---- 11.1 初始化 ----
    def init(self) -> dict[str, Any]:
        """git init（本地仓库；无 remote；hooks 指向空目录禁用）。"""
        if (self._worktree / ".git").exists():
            return {"ok": True, "already_initialized": True}
        # 11.1：不继承 credential helper（环境变量白名单之外）；身份用本地项目身份
        result = self._runner.run("git_init", ["-b", "main"], cwd_alias="worktree")
        if result.return_code != 0:
            raise SandboxGitError(f"git init failed: {result.stderr[:200]}")
        # 11.4：禁用 hooks（指向空目录，不执行源项目附带 hooks）
        hooks_dir = self._worktree.parent / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        self._runner.run("git_config", ["core.hooksPath", str(hooks_dir)])
        self._runner.run("git_config", ["user.name", self._identity[0]])
        self._runner.run("git_config", ["user.email", self._identity[1]])
        return {"ok": True, "git_initialized": True, "hooks_disabled": True}

    # ---- 11.2 允许操作 ----
    def status(self) -> dict[str, Any]:
        r = self._runner.run("git_status", [], cwd_alias="worktree")
        return {"return_code": r.return_code, "stdout": r.stdout, "stderr": r.stderr}

    def diff(self) -> dict[str, Any]:
        r = self._runner.run("git_diff", [], cwd_alias="worktree")
        return {"return_code": r.return_code, "stdout": r.stdout, "stderr": r.stderr}

    def diff_check(self) -> dict[str, Any]:
        r = self._runner.run("git_diff_check", [], cwd_alias="worktree")
        return {"return_code": r.return_code, "stdout": r.stdout, "stderr": r.stderr}

    def log(self) -> dict[str, Any]:
        r = self._runner.run("git_log", [], cwd_alias="worktree")
        return {"return_code": r.return_code, "stdout": r.stdout, "stderr": r.stderr}

    def add(self, paths: list[str]) -> dict[str, Any]:
        """add 指定路径（11.2；拒绝 . 全量以外的危险目标不在此列，路径必须 worktree 内）。"""
        if not paths or any(p.startswith(("-", "/")) for p in paths):
            raise SandboxGitError("invalid add paths")
        r = self._runner.run("git_add", paths, cwd_alias="worktree")
        return {"return_code": r.return_code, "stdout": r.stdout, "stderr": r.stderr}

    # ---- 11.5 本地 commit（explicit approval 绑定） ----
    def commit(self, approval_id: str, message: str, tests_passed: bool = False) -> dict[str, Any]:
        """本地 commit：校验审批（approved + 未过期）→ 执行 → Commit Artifact。"""
        request = self._approval.get(approval_id)
        if request is None:
            raise SandboxGitError("approval not found for git commit")
        if request.action_type != "git_commit":
            raise SandboxGitError("approval not bound to git commit")
        try:
            self._approval.verify_execution(
                request,
                parameter_hash=request.parameter_hash,
                target_hash="",
                operation_hash=request.operation_hash,
            )
        except ApprovalError as exc:
            raise SandboxGitError(f"approval invalid: {exc}") from exc
        if not message.strip() or len(message) > 200:
            raise SandboxGitError("invalid commit message")
        r = self._runner.run("git_commit", [message], cwd_alias="worktree")
        if r.return_code != 0:
            return {"ok": False, "return_code": r.return_code, "stderr": r.stderr}
        # 收集 commit 信息（本地，无远程）
        sha_result = self._runner.run("git_rev_parse", ["HEAD"])
        sha = sha_result.stdout.strip() if sha_result.return_code == 0 else ""
        diff_result = self.diff()
        artifact = self._artifacts.write(
            artifact_type="git_commit",
            content=json.dumps(
                {
                    "commit_sha": sha,
                    "message": message,
                    "changed_files": self._changed_files(),
                    "diff_hash": diff_result.get("stdout", ""),
                    "approval_id": approval_id,
                    "tests_passed": tests_passed,
                    "remote": None,
                    "pushed": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            task_id=request.task_id,
            subtask_id=request.subtask_id,
            created_by="executor",
            approval_id=approval_id,
        )
        return {
            "ok": True,
            "commit_sha": sha,
            "local_only": True,
            "pushed": False,
            "artifact_id": artifact.artifact_id,
        }

    def _changed_files(self) -> list[str]:
        r = self._runner.run("git_show", ["--name-only", "--format=", "HEAD"], cwd_alias="worktree")
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    # ---- 11.3 禁止操作（显式拒绝） ----
    def assert_no_remote(self) -> None:
        r = self._runner.run("git_remote", [], cwd_alias="worktree")
        if r.stdout.strip():
            raise SandboxGitError("sandbox repo must not have remotes")
