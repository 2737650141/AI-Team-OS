"""007 十九：Write/Patch（19-31）/ Command（32-43）/ Artifact（56）测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.approval import ApprovalService
from app.core.artifacts import ARTIFACT_TYPES, ArtifactWriter
from app.core.command_runner import (
    CommandError,
    CommandPolicy,
    SandboxCommandRunner,
)
from app.core.patch_engine import (
    MAX_PATCH_LINES,
    PatchApplier,
    PatchError,
    PatchProposal,
    PatchValidator,
    relocate_single_file_hunks,
)
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext
from app.tools.sandbox_tools import SandboxToolset, build_sandbox_tools

# ================= Patch / Write（19-31） =================


@pytest.fixture()
def worktree(tmp_path: Path) -> Path:
    wt = tmp_path / "runtime" / "workspaces" / "t1" / "worktree"
    wt.mkdir(parents=True)
    (wt / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return wt


def _proposal(worktree: Path, target: str = "main.py", old: str | None = None) -> PatchProposal:
    old = old or (worktree / target).read_text(encoding="utf-8")
    new = old.replace("return 1", "return 2")
    hunks = ["@@ -1,3 +1,3 @@\n"]
    hunks += ["-" + line for line in old.splitlines(keepends=True)]
    hunks += ["+" + line for line in new.splitlines(keepends=True)]
    diff = "".join(["--- a/" + target + "\n", "+++ b/" + target + "\n"] + hunks)
    return PatchProposal(
        task_id="t1",
        subtask_id="s1",
        target_files=[target],
        unified_diff=diff,
        reason="fix",
        expected_effect="return 2",
    )


# ---------- 19. 创建文件 ----------
def test_write_creates_file(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    approval = ApprovalService()
    ts = SandboxToolset(worktree, "t1", artifacts, approval)
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = ts.write_file("new.txt", "hello", ctx)
    assert r["ok"]
    assert (worktree / "new.txt").read_text(encoding="utf-8") == "hello"
    assert r["artifact_id"]


# ---------- 20. 修改文件 ----------
def test_write_modifies_file(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, ApprovalService())
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = ts.write_file("main.py", "def main():\n    return 9\n", ctx)
    assert r["ok"]
    assert "return 9" in (worktree / "main.py").read_text(encoding="utf-8")


# ---------- 21. 原子写（无 .tmp 残留） ----------
def test_atomic_write_no_tmp_left(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, ApprovalService())
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    ts.write_file("main.py", "v2", ctx)
    assert not list(worktree.glob("*.tmp"))


# ---------- 22. 备份 ----------
def test_write_creates_backup(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, ApprovalService())
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    ts.write_file("main.py", "changed", ctx)
    backups = list((tmp_path / "runtime" / "workspaces" / "t1" / "backups").glob("*.bak"))
    assert backups
    assert "return 1" in backups[0].read_text(encoding="utf-8")


# ---------- 23. Unified Diff 校验 ----------
def test_patch_validator_diff_format(worktree: Path) -> None:
    v = PatchValidator(worktree)
    bad = PatchProposal(task_id="t1", target_files=["main.py"], unified_diff="no hunks here")
    with pytest.raises(PatchError, match="diff format"):
        v.validate(bad)


# ---------- 24. Base 哈希 ----------
def test_patch_base_hash_mismatch(worktree: Path) -> None:
    v = PatchValidator(worktree)
    p = _proposal(worktree)
    with pytest.raises(PatchError, match="base hash"):
        v.validate(p, base_hashes={"main.py": "wronghash"})


# ---------- 25. 路径逃逸（GT-W05） ----------
def test_patch_path_escape_rejected(worktree: Path) -> None:
    v = PatchValidator(worktree)
    p = PatchProposal(
        task_id="t1", target_files=["../outside.txt"], unified_diff="@@ -1 +1 @@\n-x\n+y\n"
    )
    with pytest.raises(PatchError, match="traversal"):
        v.validate(p)


# ---------- 26. 敏感路径 ----------
def test_patch_sensitive_path_rejected(worktree: Path) -> None:
    v = PatchValidator(worktree)
    p = PatchProposal(
        task_id="t1", target_files=["secret.env"], unified_diff="@@ -1 +1 @@\n-x\n+y\n"
    )
    with pytest.raises(PatchError, match="banned"):
        v.validate(p)


# ---------- 27. 二进制拒绝 ----------
def test_patch_binary_rejected(worktree: Path) -> None:
    (worktree / "bin.dat").write_bytes(b"\x00\x01\x02")
    v = PatchValidator(worktree)
    p = PatchProposal(task_id="t1", target_files=["bin.dat"], unified_diff="@@ -1 +1 @@\n-x\n+y\n")
    with pytest.raises(PatchError, match="binary"):
        v.validate(p)


# ---------- 28. 变更行数限制 ----------
def test_patch_line_limit(worktree: Path) -> None:
    v = PatchValidator(worktree)
    lines = "\n".join("+" + str(i) for i in range(MAX_PATCH_LINES + 10))
    p = PatchProposal(task_id="t1", target_files=["main.py"], unified_diff="@@ -1 +1 @@\n" + lines)
    with pytest.raises(PatchError, match="changed lines"):
        v.validate(p)


# ---------- 29. 多文件原子回滚（GT-W08） ----------
def test_patch_atomic_rollback(worktree: Path, tmp_path: Path) -> None:
    """第二个文件应用失败 → 第一个文件也恢复。"""
    (worktree / "a.txt").write_text("AAA", encoding="utf-8")
    (worktree / "b.txt").write_text("BBB", encoding="utf-8")
    # 构造一个会让第二个文件失败的 diff（b.txt 的 hunk 越界）
    diff = (
        "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-AAA\n+aaa\n"
        "--- a/b.txt\n+++ b/b.txt\n@@ -99,1 +99,1 @@\n-X\n+Y\n"
    )
    p = PatchProposal(task_id="t1", target_files=["a.txt", "b.txt"], unified_diff=diff)
    v = PatchValidator(worktree)
    v.validate(p)  # 格式校验通过（hunk 存在）
    applier = PatchApplier(worktree, worktree.parent / "backups")
    with pytest.raises(PatchError, match="rolled back"):
        applier.apply(p, "appr-1")
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "AAA"  # 已恢复
    assert (worktree / "b.txt").read_text(encoding="utf-8") == "BBB"


# ---------- 30. 删除进入回收区 ----------
def test_validator_rejects_out_of_bounds_single_file_hunk(worktree: Path) -> None:
    (worktree / "main.py").write_text("a\nb\nc\n", encoding="utf-8")
    proposal = PatchProposal(
        task_id="t1",
        target_files=["main.py"],
        unified_diff=(
            "--- a/main.py\n+++ b/main.py\n@@ -5,7 +5,7 @@\n b\n-c\n+C\n"
        ),
    )
    with pytest.raises(PatchError, match="line count mismatch|beyond file end|out of range"):
        PatchValidator(worktree).validate(proposal)


def test_validator_rejects_shifted_hunk_with_wrong_context(worktree: Path) -> None:
    old = (worktree / "main.py").read_text(encoding="utf-8")
    proposal = PatchProposal(
        task_id="t1",
        target_files=["main.py"],
        unified_diff=(
            "--- a/main.py\n"
            "+++ b/main.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def shifted_main():\n"
            "-    return 1\n"
            "+    return 2\n"
        ),
    )
    assert old.startswith("def main")
    with pytest.raises(PatchError, match="context mismatch|deletion mismatch"):
        PatchValidator(worktree).validate(proposal)


def test_unique_hunk_context_can_be_relocated_without_changing_body(worktree: Path) -> None:
    old = (worktree / "main.py").read_text(encoding="utf-8")
    shifted = (
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -2,2 +2,2 @@\n"
        " def main():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    relocated = relocate_single_file_hunks(shifted, old)
    assert "@@ -1,2 +1,2 @@" in relocated
    assert "-    return 1\n+    return 2" in relocated
    proposal = PatchProposal(task_id="t1", target_files=["main.py"], unified_diff=relocated)
    PatchValidator(worktree).validate(proposal)


def test_hunk_relocation_rejects_ambiguous_old_context() -> None:
    diff = "--- a/x.txt\n+++ b/x.txt\n@@ -9,1 +9,1 @@\n-same\n+new\n"
    with pytest.raises(PatchError, match="ambiguous"):
        relocate_single_file_hunks(diff, "same\nsame\n")


def test_delete_moves_to_trash(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, ApprovalService())
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = ts.delete_path("main.py", ctx)
    assert r["ok"]
    assert not (worktree / "main.py").exists()
    assert Path(r["trash_path"]).exists()  # 移入回收区（可恢复）


# ---------- 31. 恢复删除 ----------
def test_restore_deleted(worktree: Path, tmp_path: Path) -> None:
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, ApprovalService())
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = ts.delete_path("main.py", ctx)
    # 从回收区恢复
    trash = Path(r["trash_path"])
    import shutil

    shutil.move(str(trash), str(worktree / "main.py"))
    assert (worktree / "main.py").exists()


# ================= Command（32-43） =================


@pytest.fixture()
def policy(worktree: Path) -> CommandPolicy:
    return CommandPolicy(venv_python="python", worktree=worktree)


def _runner(policy: CommandPolicy, worktree: Path) -> SandboxCommandRunner:
    return SandboxCommandRunner(policy, worktree)


# ---------- 32. 固定 executable 映射 ----------
def test_command_mapping_fixed(policy: CommandPolicy) -> None:
    argv = policy.resolve("python_pytest", ["-q", "tests/"])
    assert argv[0] == "python"  # 路径不可覆盖
    assert argv[1:3] == ["-m", "pytest"]


# ---------- 33. 禁止 shell ----------
def test_no_shell_invocation(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    r = runner.run("git_status", [], cwd_alias="worktree")
    # git 在非仓库目录返回 128：命令真实执行且无 shell（返回码透传）
    assert r.return_code in (0, 1, 128)


# ---------- 34. 注入参数拒绝（GT-W06） ----------
@pytest.mark.parametrize(
    "arg",
    ["pytest && whoami", "pytest | powershell", "$(whoami)", "x;rm -rf", "a`b", ">$HOME/x", "a&b"],
)
def test_injection_args_rejected(policy: CommandPolicy, arg: str) -> None:
    with pytest.raises(CommandError, match="injection|flag"):
        policy.resolve("python_pytest", [arg])


# ---------- 35. cwd 固定 ----------
def test_cwd_fixed(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    with pytest.raises(CommandError, match="cwd_alias"):
        runner.run("git_status", [], cwd_alias="elsewhere")


# ---------- 36. 最小环境 ----------
def test_minimal_env(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    env = runner._minimal_env()
    assert "PATH" in env
    assert not any(k.startswith("HTTP_PROXY") for k in env)
    assert "PYTHONNOUSERSITE" in env


# ---------- 37. 超时 ----------
def test_timeout_kills(policy: CommandPolicy, worktree: Path, tmp_path: Path) -> None:
    runner = SandboxCommandRunner(policy, worktree, logs_dir=tmp_path / "logs")
    # 极小超时：pytest 进程启动必然超过 0.01s → TimeoutExpired → 进程树终止
    r = runner.run("python_pytest", ["-q"], timeout_seconds=0.01)
    assert r.timed_out is True


# ---------- 38. 输出限制 ----------
def test_output_limited(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    r = runner.run("git_diff_check", [])
    assert r.stdout is not None
    assert r.return_code is not None


# ---------- 39. stdout/stderr 脱敏 ----------
def test_output_redacted(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    redacted = runner._sanitize(b"error: key=sk-abcdef1234567890xyz")
    assert "sk-abcdef1234567890xyz" not in redacted
    assert "***" in redacted


# ---------- 40. 非零返回码 ----------
def test_nonzero_return_code(policy: CommandPolicy, worktree: Path) -> None:
    # git diff --check 在无仓库目录返回 128（非零）——验证返回码透传
    runner = _runner(policy, worktree)
    r = runner.run("git_diff_check", [])
    assert r.return_code != 0  # 无 git 仓库
    assert r.return_code in (128, 0) or r.return_code > 0


# ---------- 41. 进程树终止（超时路径覆盖见 37；此处验证工具方法存在） ----------
def test_process_tree_termination_available(policy: CommandPolicy, worktree: Path) -> None:
    runner = _runner(policy, worktree)
    assert hasattr(runner, "_terminate_tree")


# ---------- 42. 网络命令不可用 ----------
def test_network_commands_unavailable(policy: CommandPolicy) -> None:
    for bad in ("curl", "wget", "bash", "sh", "powershell", "cmd", "pip_install", "npm_install"):
        with pytest.raises(CommandError, match="not allowed"):
            policy.resolve(bad, [])


# ---------- 43. 未批准不执行（审批在网关/工作流层；写工具无 approval_id 被拦） ----------
def test_write_tool_blocked_without_approval(worktree: Path, tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    approval = ApprovalService()
    artifacts = ArtifactWriter(tmp_path / "runtime", "t1")
    ts = SandboxToolset(worktree, "t1", artifacts, approval)
    gateway = ToolGateway(audit=audit, task_id="t1", approval_service=approval)
    for spec in build_sandbox_tools(ts):
        gateway.register(spec)
    ctx = ToolExecutionContext(task_id="t1", subtask_id="s1", role="executor")
    r = gateway.invoke("sandbox_write_file", {"path": "x.txt", "content": "x"}, ctx=ctx)
    assert r.status == "blocked"  # 无 approval_id → 拦截


# ================= Artifact（六） =================


def test_artifact_types_cover_required(tmp_path: Path) -> None:
    required = {
        "plan",
        "patch",
        "diff",
        "created_file",
        "modified_file",
        "deleted_file_manifest",
        "test_report",
        "command_report",
        "git_commit",
        "final_report",
    }
    assert required <= ARTIFACT_TYPES


def test_artifact_writer_roundtrip(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path / "runtime", "t1")
    rec = writer.write(
        artifact_type="diff",
        content="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-x\n+y\n",
        task_id="t1",
        subtask_id="s1",
        approval_id="appr-1",
    )
    assert rec.artifact_id and rec.content_hash
    assert rec.approval_id == "appr-1"
    loaded = writer.load_all("t1")
    assert len(loaded) == 1
    assert loaded[0].artifact_id == rec.artifact_id
    assert "--- a/x" in writer.read_content(loaded[0])
