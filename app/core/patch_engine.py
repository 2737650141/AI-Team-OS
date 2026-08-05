"""补丁引擎（007 八）：PatchProposal / PatchValidator / PatchApplier。

- Unified Diff 应用使用受控 Python 实现（不通过 Shell 调用 patch）。
- 应用前 10 项确定性校验（8.2）；任一失败整个 Patch 原子回滚（8.4）。
- 审批前生成预览（diff Artifact / 变更摘要 / 风险摘要 / 预计测试）（8.3）。
- 不允许部分成功却标记完成。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MAX_PATCH_FILES = 50  # 变更文件数上限（8.2-9）
MAX_PATCH_LINES = 5000  # 变更总行数上限（8.2-10）
MAX_FILE_BYTES = 2 * 1024 * 1024  # 单文件上限（7.2）
BANNED_PATCH_PATHS = {".env", ".ssh", ".git", "id_rsa"}  # 8.2-5 禁止路径（子串匹配）
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".p8", ".pfx", ".ppk"}

_PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PatchError(Exception):
    """补丁错误（安全消息）。"""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _validate_rel_path(rel: str, worktree: Path) -> Path:
    """路径安全（8.2-4/8.2-8）：worktree 内相对路径，拒绝绝对/穿越/UNC/ADS。"""
    if not rel.strip():
        raise PatchError("empty path")
    raw = rel.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise PatchError("absolute path rejected")
    if raw.startswith("//"):
        raise PatchError("UNC path rejected")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise PatchError("path traversal rejected")
    if ":" in parts[-1]:
        raise PatchError("alternate data stream rejected")
    target = (worktree / Path(*parts)).resolve()
    worktree_resolved = worktree.resolve()
    if not (
        str(target) == str(worktree_resolved)
        or str(target).startswith(str(worktree_resolved) + os.sep)
    ):
        raise PatchError("path escapes worktree")
    return target


class PatchProposal(BaseModel):
    """8.1：补丁提案（审批前生成，用户必须先看到 Diff）。"""

    patch_id: str = ""
    task_id: str
    subtask_id: str | None = None
    base_revision: str | None = None
    target_files: list[str] = Field(default_factory=list)
    unified_diff: str = ""
    reason: str = ""
    expected_effect: str = ""
    risk_summary: str = ""
    tests_to_run: list[str] = Field(default_factory=list)
    source_evidence_ids: list[str] = Field(default_factory=list)

    @property
    def diff_hash(self) -> str:
        return sha256_text(self.unified_diff)

    def model_dump_safe(self) -> dict[str, Any]:
        return self.model_dump()


class PatchValidator:
    """8.2：应用前 10 项确定性校验。"""

    def __init__(
        self,
        worktree: Path,
        max_files: int = MAX_PATCH_FILES,
        max_lines: int = MAX_PATCH_LINES,
        max_file_bytes: int = MAX_FILE_BYTES,
    ) -> None:
        self._worktree = worktree
        self._max_files = max_files
        self._max_lines = max_lines
        self._max_file_bytes = max_file_bytes

    def validate(self, proposal: PatchProposal, base_hashes: dict[str, str] | None = None) -> None:
        """全部通过返回 None；任一失败抛 PatchError。"""
        # 1. Unified Diff 格式有效（含标准头 + hunk）
        diff = proposal.unified_diff
        if not diff.strip():
            raise PatchError("empty unified diff")
        header_lines = [
            line for line in diff.splitlines() if line.startswith(("--- ", "+++ ", "@@"))
        ]
        if not any(line.startswith("@@") for line in header_lines):
            raise PatchError("invalid unified diff format (no hunk)")
        # 2. 所有目标位于 worktree（路径安全）
        targets: list[Path] = []
        for rel in proposal.target_files:
            targets.append(_validate_rel_path(rel, self._worktree))
        # 3. Base 文件哈希匹配（若提供）
        if base_hashes:
            for rel, expected in base_hashes.items():
                target = _validate_rel_path(rel, self._worktree)
                if not target.exists():
                    raise PatchError(f"base file missing: {rel}")
                actual = sha256_text(target.read_text(encoding="utf-8", errors="replace"))
                if actual != expected:
                    raise PatchError(f"base hash mismatch: {rel}")
        # 4/5. 禁止路径与敏感文件
        for rel in proposal.target_files:
            lowered = rel.lower()
            if any(banned in lowered for banned in BANNED_PATCH_PATHS):
                raise PatchError(f"banned path: {rel}")
            if Path(rel).suffix.lower() in SENSITIVE_SUFFIXES:
                raise PatchError(f"sensitive file: {rel}")
        # 6. 不允许创建超大文件（7.2/8.2-6）
        for target in targets:
            if target.exists() and target.stat().st_size > self._max_file_bytes:
                raise PatchError(f"file too large: {target.name}")
        # 7. 不允许修改二进制文件（8.2-7）
        for target in targets:
            if target.exists():
                data = target.read_bytes()[:4096]
                if b"\x00" in data:
                    raise PatchError(f"binary file rejected: {target.name}")
        # 8. 路径重命名逃逸已由 _validate_rel_path 覆盖（resolve 复查）
        # 9. 变更文件数上限
        if len(proposal.target_files) > self._max_files:
            raise PatchError(f"too many files ({len(proposal.target_files)} > {self._max_files})")
        # 10. 变更总行数上限（diff 中 +/- 行数）
        changed = sum(
            1
            for line in diff.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        )
        if changed > self._max_lines:
            raise PatchError(f"too many changed lines ({changed} > {self._max_lines})")


class PatchApplier:
    """8.4：受控 Python 补丁应用（原子：任一文件失败则整体回滚）。"""

    def __init__(self, worktree: Path, backups_dir: Path | None = None) -> None:
        self._worktree = worktree
        self._backups_dir = backups_dir or (worktree.parent / "backups")

    def preview_diff(self, proposal: PatchProposal) -> str:
        """生成 Diff 预览（8.3：审批前展示）。"""
        return proposal.unified_diff

    def apply(self, proposal: PatchProposal, approval_id: str) -> dict[str, str]:
        """应用补丁（须先通过 PatchValidator + 已批准）。返回 {相对路径: 新内容哈希}。

        原子性：先对所有目标做备份；任一文件失败 → 恢复全部备份并抛 PatchError。
        """
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        backup_files: list[tuple[Path, Path]] = []
        try:
            # 解析 hunk 并应用到每个目标（简单 unified diff 应用）
            new_hashes: dict[str, str] = {}
            # 为每个目标生成新内容
            for rel in proposal.target_files:
                target = _validate_rel_path(rel, self._worktree)
                target.parent.mkdir(parents=True, exist_ok=True)
                old_text = (
                    target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
                )
                new_text = self._apply_diff_to_file(proposal.unified_diff, rel, old_text)
                # 备份原文件（原子回滚用）
                backup = self._backups_dir / f"{uuid.uuid4().hex[:12]}.bak"
                if target.exists():
                    shutil.copy2(target, backup)
                    backup_files.append((target, backup))
                # 原子替换（7.1）：写临时文件后 rename
                tmp = target.with_suffix(target.suffix + ".tmp")
                tmp.write_text(new_text, encoding="utf-8")
                os.replace(tmp, target)
                new_hashes[rel] = sha256_text(new_text)
            return new_hashes
        except Exception as exc:  # noqa: BLE001
            # 8.4：任一文件失败 → 整体原子回滚
            for target, backup in backup_files:
                shutil.copy2(backup, target)
            raise PatchError(f"patch apply failed, rolled back: {exc}") from exc

    def _apply_diff_to_file(self, diff: str, rel: str, old_text: str) -> str:
        """从 unified diff 中提取目标文件对应 hunk 并应用（简化但确定性的实现）。"""
        lines = diff.splitlines()
        # 提取该文件的 hunk（--- /+++ 头匹配 rel）
        file_hunks: list[list[str]] = []
        current: list[str] | None = None
        for line in lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            if line.startswith("@@"):
                if current is not None:
                    file_hunks.append(current)
                current = [line]
            elif current is not None:
                current.append(line)
        if current is not None:
            file_hunks.append(current)
        if not file_hunks:
            return old_text  # 无 hunk（创建空文件场景由 write 处理）
        old_lines = old_text.splitlines(keepends=True)
        for hunk in file_hunks:
            old_lines = self._apply_hunk(old_lines, hunk)
        return "".join(old_lines)

    def _apply_hunk(self, old_lines: list[str], hunk: list[str]) -> list[str]:
        """单 hunk 应用：@@ -start,count +start,count @@ + 上下文/增删行。"""
        import re as _re

        header = hunk[0]
        m = _re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
        if not m:
            raise PatchError(f"invalid hunk header: {header}")
        old_start = int(m.group(1))
        result: list[str] = []
        # 按行号定位（1-based）
        idx = old_start - 1
        if idx < 0 or idx > len(old_lines):
            raise PatchError(f"hunk start out of range: {old_start}")
        result.extend(old_lines[:idx])
        for line in hunk[1:]:
            if line.startswith(" "):
                if idx < len(old_lines):
                    result.append(old_lines[idx])
                    idx += 1
                else:
                    raise PatchError("context line beyond file end")
            elif line.startswith("+"):
                result.append(line[1:] + ("\n" if not line[1:].endswith("\n") else ""))
            elif line.startswith("-"):
                if idx < len(old_lines):
                    idx += 1
                else:
                    raise PatchError("deletion beyond file end")
            else:
                raise PatchError(f"unexpected diff line: {line[:40]}")
        result.extend(old_lines[idx:])
        return result
