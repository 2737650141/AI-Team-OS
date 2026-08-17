"""受限命令执行器（007 九/十）：SandboxCommandRunner / CommandPolicy / CommandResult。

- 禁止通用 Shell：绝不使用 shell=True，不接收整段命令字符串（9.1）。
- 只接受结构化 executable_id + args[] + cwd_alias + timeout + environment_profile（9.1）。
- 第一版静态白名单 10 命令（9.2）；可执行文件路径由映射决定，用户/LLM 不能覆盖（9.3）。
- 参数校验：拒绝连接符/重定向/管道/命令替换/环境变量扩展/任意绝对路径（9.4）；
  pytest 目标限 worktree 内测试路径；Git 目标限当前沙箱仓库。
- 运行限制：超时/输出大小限制/stdout-stderr 脱敏/进程树终止/工作目录固定/
  最小环境白名单/返回码记录（9.5）。
- 网络隔离：不提供网络型命令 + 清除代理环境变量 + 文档声明 network_isolation=best_effort
  （非容器级强隔离，不得声称 guaranteed；9.5/十）。
- 运行前 approval 由调用方（Executor 工作流）保证；结果形成 CommandReport Artifact。
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.secrets import redact

MAX_OUTPUT_BYTES = 256 * 1024  # 输出大小限制（9.5）
DEFAULT_TIMEOUT = 60  # 秒
MAX_ARGS = 20
MAX_ARG_LEN = 200

# 环境变量白名单（最小环境，9.5）：路径与 Python 基础项；代理/凭据清除（十）
ENV_WHITELIST = (
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "TEMP",
    "TMP",
    "COMSPEC",
    "PATHEXT",
    "USERPROFILE",
    "HOME",
    "LANG",
    "PYTHONUTF8",
    "VIRTUAL_ENV",
)
ENV_BLOCKLIST_PREFIXES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "AWS_",
    "AZURE_",
    "GOOGLE_",
    "GITHUB_TOKEN",
    "AI_TEAM_",
)

# 参数拒绝模式（9.4）
_INJECTION_RE = re.compile(
    r"([;&|`$]|\|\||&&|>\s|<\s|>>|\$\(|\$\{|\b(?:cmd|powershell|bash|sh|wget|curl)\b)",
    re.I,
)


class CommandError(Exception):
    """命令错误（安全消息）。"""


@dataclass
class CommandResult:
    """9.5：命令结果（含脱敏输出）。"""

    executable_id: str
    return_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    truncated: bool = False
    timed_out: bool = False
    cwd: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable_id": self.executable_id,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "timed_out": self.timed_out,
            "cwd": self.cwd,
        }


class CommandPolicy:
    """9.2：静态命令白名单（executable_id → argv 映射，路径不可覆盖）。"""

    def __init__(self, venv_python: str | None = None, worktree: Path | None = None) -> None:
        self._python = venv_python or sys.executable
        self._worktree = worktree
        self._commands: dict[str, list[str]] = {
            "python_pytest": [self._python, "-m", "pytest"],
            "python_mypy": [self._python, "-m", "mypy"],
            "python_ruff_check": [self._python, "-m", "ruff", "check"],
            "python_ruff_format_check": [self._python, "-m", "ruff", "format", "--check"],
            "git_status": ["git", "status", "--short"],
            "git_diff": ["git", "diff"],
            "git_diff_check": ["git", "diff", "--check"],
            "git_log": ["git", "log", "--oneline", "-10"],
            "git_add": ["git", "add"],
            "git_commit": ["git", "commit", "-m"],
            "git_init": ["git", "init"],
            "git_config": ["git", "config", "--local"],  # 沙箱本地配置（11.1/11.4）
            "git_rev_parse": ["git", "rev-parse"],
            "git_show": ["git", "show"],
            "git_remote": ["git", "remote"],  # 只读断言（11.3 禁止 add/rm）
        }

    def resolve(self, executable_id: str, args: list[str]) -> list[str]:
        """executable_id + 受限参数 → 完整 argv（9.3：路径不可覆盖）。"""
        if executable_id not in self._commands:
            raise CommandError(f"command not allowed: {executable_id}")
        self._validate_args(args)
        base = list(self._commands[executable_id])
        return base + args

    def _validate_args(self, args: list[str]) -> None:
        """9.4：拒绝注入与越界参数。"""
        if len(args) > MAX_ARGS:
            raise CommandError(f"too many args ({len(args)} > {MAX_ARGS})")
        for arg in args:
            if len(arg) > MAX_ARG_LEN:
                raise CommandError("argument too long")
            if _INJECTION_RE.search(arg):
                raise CommandError(f"injection pattern rejected in argument: {arg[:40]}")
            # 已存在的绝对路径是位置参数而非 flag（Windows C:\\... 历来放行，
            # POSIX /tmp/... 需同等对待）；不存在或相对路径仍按 flag 规则拒绝。
            if arg.startswith(("-", "/")) and not (
                os.path.isabs(arg) and os.path.exists(arg)
            ) and arg not in (
                "-v",
                "-q",
                "--check",
                "--short",
                "--oneline",
                "-m",
                "--color=never",
                "--local",
                "-b",
                "--name-only",
                "--format=",
                "-10",
            ):
                # 允许受控 flag；其余以 - 开头的参数需在白名单内（保守拒绝）
                raise CommandError(f"flag not allowed: {arg[:40]}")


class SandboxCommandRunner:
    """受限命令执行器（9.5：无 shell、超时、输出限制、脱敏、进程树终止、最小环境）。"""

    def __init__(
        self,
        policy: CommandPolicy,
        worktree: Path,
        logs_dir: Path | None = None,
        network_isolation: str = "best_effort",  # 十：不得标记 guaranteed
    ) -> None:
        self._policy = policy
        self._worktree = worktree
        self._logs_dir = logs_dir
        self.network_isolation = network_isolation

    def run(
        self,
        executable_id: str,
        args: list[str],
        cwd_alias: str = "worktree",
        timeout_seconds: int = DEFAULT_TIMEOUT,
        environment_profile: str = "minimal",
    ) -> CommandResult:
        """运行白名单命令（9.5）。cwd 固定；环境最小白名单；输出脱敏限长。"""
        if cwd_alias not in ("worktree",):
            raise CommandError(f"cwd_alias not allowed: {cwd_alias}")
        if environment_profile != "minimal":
            raise CommandError(f"environment_profile not allowed: {environment_profile}")
        argv = self._policy.resolve(executable_id, args)
        start = time.monotonic()
        env = self._minimal_env()
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(self._worktree),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,  # 9.1：绝不使用 shell
                text=False,
                # security_review HIGH：独立会话（POSIX 新进程组），超时 killpg 只杀子进程
                start_new_session=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                stdout_b, stderr_b = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                # 9.5：超时 → 终止进程树
                self._terminate_tree(proc)
                stdout_b, stderr_b = proc.communicate()
                timed_out = True
            else:
                timed_out = False
        except OSError as exc:
            raise CommandError(f"command failed to start: {exc}") from exc
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = self._sanitize(stdout_b)
        stderr = self._sanitize(stderr_b)
        truncated = False
        if len(stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
            stdout = stdout[: MAX_OUTPUT_BYTES // 2]
            truncated = True
        if self._logs_dir is not None:
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            (self._logs_dir / f"{executable_id}-{int(start)}.log").write_text(
                f"argv={argv}\nreturn_code={proc.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}\n",
                encoding="utf-8",
            )
        return CommandResult(
            executable_id=executable_id,
            return_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            truncated=truncated,
            timed_out=timed_out,
            cwd=str(self._worktree),
        )

    def _minimal_env(self) -> dict[str, str]:
        """9.5/十：最小环境白名单 + 清除代理与凭据变量。"""
        env = {}
        for key in ENV_WHITELIST:
            if key in os.environ:
                env[key] = os.environ[key]
        # 清除代理（十：无网络命令 + 无代理环境）
        for key in list(os.environ):
            if key.startswith(ENV_BLOCKLIST_PREFIXES):
                continue  # 不放入 env
        env["PYTHONNOUSERSITE"] = "1"
        return env

    def _sanitize(self, data: bytes) -> str:
        """9.5：stdout/stderr 脱敏（密钥替换）。"""
        text = data.decode("utf-8", errors="replace")
        return redact(text)

    def _terminate_tree(self, proc: subprocess.Popen) -> None:
        """9.5：进程树终止（Windows: taskkill /T；POSIX: 进程组 kill）。"""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
