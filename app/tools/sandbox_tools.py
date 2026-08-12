"""沙箱写工具（007 七）：sandbox_create_directory / write_file / apply_patch /
copy_file / move_file / delete_path / restore_backup。

通用限制（7.1）：
- 只能操作当前任务 worktree；禁止绝对路径/../符号链接-Junction 逃逸/UNC/设备路径/ADS。
- 禁止覆盖敏感配置（.env*/密钥/.git）。
- 写入前后计算哈希；原子替换（临时文件+os.replace）；修改前创建备份；失败回滚。
- 全部结果形成 Artifact。
- 删除为 dangerous + explicit approval；默认移入任务回收区（trash/），可恢复。
- 二进制写入默认禁止；可执行文件创建默认禁止（7.2）。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.core.approval import ApprovalService
from app.core.artifacts import ArtifactWriter
from app.core.patch_engine import (
    MAX_FILE_BYTES,
    PatchApplier,
    PatchProposal,
    PatchValidator,
)
from app.gateway.tool_policy import ToolExecutionContext
from app.tools.spec import RiskLevel, ToolSpec

MAX_NEW_FILES = 100  # 最大新增文件数量（7.2）
MAX_TOTAL_WRITE_BYTES = 10 * 1024 * 1024  # 单任务总写入量（7.2）

_PATH_SAFE_RE = re.compile(r"^[A-Za-z0-9_./-]+$")
_SENSITIVE_NAMES = (".env", ".ssh", ".git", "id_rsa", "id_ed25519", "credentials", "secrets")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _validate_worktree_path(rel: str, worktree: Path) -> Path:
    """7.1：worktree 内相对路径（复用补丁引擎的路径安全规则）。"""
    from app.core.patch_engine import _validate_rel_path

    return _validate_rel_path(rel, worktree)


def _check_sensitive(rel: str) -> None:
    lowered = rel.lower()
    for name in _SENSITIVE_NAMES:
        if name in lowered:
            raise PermissionError(f"sensitive path rejected: {rel}")


class SandboxToolset:
    """沙箱写工具集（7.x）。全部要求 ctx.approval_id（网关放行）+ Artifact 固化。"""

    def __init__(
        self,
        worktree: Path,
        task_id: str,
        artifacts: ArtifactWriter,
        approval: ApprovalService,
        backups_dir: Path | None = None,
        trash_dir: Path | None = None,
        write_budget_bytes: int = MAX_TOTAL_WRITE_BYTES,
    ) -> None:
        self._worktree = worktree
        self._task_id = task_id
        self._artifacts = artifacts
        self._approval = approval
        self._backups = backups_dir or (worktree.parent / "backups")
        self._trash = trash_dir or (worktree.parent / "trash")
        self._written_bytes = 0
        self._max_write = write_budget_bytes

    # ---- 通用 ----
    def _track_write(self, content: str) -> None:
        self._written_bytes += len(content.encode("utf-8"))
        if self._written_bytes > self._max_write:
            raise PermissionError("total write budget exceeded")

    def _backup(self, target: Path) -> Path:
        self._backups.mkdir(parents=True, exist_ok=True)
        backup = self._backups / f"{uuid.uuid4().hex[:12]}.bak"
        if target.exists():
            shutil.copy2(target, backup)
        return backup

    def _atomic_write(self, target: Path, content: str) -> None:
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise PermissionError(f"file too large: {target.name}")
        if "\x00" in content:
            raise PermissionError("binary content rejected")
        if target.suffix.lower() in (".exe", ".dll", ".so", ".dylib", ".bin") or target.name in (
            "run.sh",
            "run.bat",
            "run.cmd",
            "start.sh",
        ):
            raise PermissionError("executable creation rejected (7.2)")
        self._backup(target)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)

    # ---- 工具 ----
    def create_directory(self, path: str, ctx: ToolExecutionContext | None) -> dict:
        try:
            _check_sensitive(path)
            target = _validate_worktree_path(path, self._worktree)
            target.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "path": str(target), "created": target.is_dir()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def write_file(self, path: str, content: str, ctx: ToolExecutionContext | None) -> dict:
        """创建/覆盖文件（7.2：原子写 + 备份 + 哈希 + Artifact）。"""
        try:
            _check_sensitive(path)
            target = _validate_worktree_path(path, self._worktree)
            was_created = not target.exists()
            self._track_write(content)
            self._atomic_write(target, content)
            artifact = self._artifacts.write(
                artifact_type="created_file" if was_created else "modified_file",
                content=content,
                task_id=self._task_id,
                subtask_id=ctx.subtask_id if ctx else None,
                created_by="executor",
                approval_id=ctx.approval_id if ctx else None,
                metadata={"path": str(target)},
            )
            return {
                "ok": True,
                "path": str(target),
                "hash": _sha256_text(content),
                "artifact_id": artifact.artifact_id,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def apply_patch(self, patch_json: str, ctx: ToolExecutionContext | None) -> dict:
        """应用 PatchProposal（JSON 字符串；须已批准且 Diff 绑定）。"""
        try:
            import json as _json

            data = _json.loads(patch_json)
            proposal = PatchProposal(**data)
            # 8.2：确定性校验（Base 哈希由调用方提供时使用 proposal.base_revision 占位）
            validator = PatchValidator(self._worktree)
            validator.validate(proposal)
            applier = PatchApplier(self._worktree, self._backups)
            approval_id = ctx.approval_id if ctx else None
            new_hashes = applier.apply(proposal, approval_id or "")
            diff_artifact = self._artifacts.write(
                artifact_type="diff",
                content=proposal.unified_diff,
                task_id=self._task_id,
                subtask_id=ctx.subtask_id if ctx else None,
                created_by="executor",
                approval_id=ctx.approval_id if ctx else None,
            )
            return {
                "ok": True,
                "new_hashes": new_hashes,
                "diff_artifact_id": diff_artifact.artifact_id,
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def copy_file(self, source: str, destination: str, ctx: ToolExecutionContext | None) -> dict:
        try:
            _check_sensitive(destination)
            src = _validate_worktree_path(source, self._worktree)
            dst = _validate_worktree_path(destination, self._worktree)
            if not src.exists():
                return {"ok": False, "error": "source not found", "code": "invalid"}
            content = src.read_text(encoding="utf-8", errors="replace")
            self._track_write(content)
            self._atomic_write(dst, content)
            return {"ok": True, "source": str(src), "destination": str(dst)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def move_file(self, source: str, destination: str, ctx: ToolExecutionContext | None) -> dict:
        try:
            _check_sensitive(destination)
            src = _validate_worktree_path(source, self._worktree)
            dst = _validate_worktree_path(destination, self._worktree)
            if not src.exists():
                return {"ok": False, "error": "source not found", "code": "invalid"}
            self._backup(src)
            self._backup(dst)
            shutil.move(str(src), str(dst))
            return {"ok": True, "source": str(src), "destination": str(dst)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def delete_path(self, path: str, ctx: ToolExecutionContext | None) -> dict:
        """删除（7.3：dangerous + explicit approval + 移入回收区，可恢复）。"""
        try:
            _check_sensitive(path)
            target = _validate_worktree_path(path, self._worktree)
            if not target.exists():
                return {"ok": False, "error": "path not found", "code": "invalid"}
            # 目录删除：文件数量与总大小上限（7.3）
            files = [p for p in target.rglob("*") if p.is_file()] if target.is_dir() else [target]
            if len(files) > 500:
                return {"ok": False, "error": "directory too large to delete", "code": "blocked"}
            # 记录删除前哈希清单
            manifest = {
                p.relative_to(self._worktree).as_posix(): _sha256_text(
                    p.read_text(encoding="utf-8", errors="replace")
                )
                for p in files
            }
            # 移入回收区（不立即物理删除，可恢复）
            trash_target = self._trash / uuid.uuid4().hex[:12] / target.name
            trash_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(trash_target))
            self._artifacts.write(
                artifact_type="deleted_file_manifest",
                content=str(manifest),
                task_id=self._task_id,
                subtask_id=ctx.subtask_id if ctx else None,
                created_by="executor",
                approval_id=ctx.approval_id if ctx else None,
                metadata={"trash_path": str(trash_target)},
            )
            return {"ok": True, "trash_path": str(trash_target), "deleted_files": list(manifest)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}

    def restore_backup(
        self, backup_name: str, target: str, ctx: ToolExecutionContext | None
    ) -> dict:
        """恢复备份（15：回滚能力）。backup_name 严格限 uuid-hex .bak（防穿越）。"""
        try:
            _check_sensitive(target)
            import re as _re

            if not _re.fullmatch(r"[0-9a-f]{12}\.bak", backup_name):
                return {"ok": False, "error": "invalid backup name", "code": "blocked"}
            backup = (self._backups / backup_name).resolve()
            backups_resolved = self._backups.resolve()
            if not (
                str(backup) == str(backups_resolved)
                or str(backup).startswith(str(backups_resolved) + os.sep)
            ):
                return {"ok": False, "error": "backup escapes backups dir", "code": "blocked"}
            if not backup.exists() or backup.suffix != ".bak":
                return {"ok": False, "error": "backup not found", "code": "invalid"}
            dst = _validate_worktree_path(target, self._worktree)
            shutil.copy2(backup, dst)
            return {"ok": True, "restored": str(dst), "from": str(backup)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "code": "blocked"}


def build_sandbox_tools(ts: SandboxToolset) -> list[ToolSpec]:
    """构造沙箱写工具集（roles=executor；requires_approval=True 由网关放行）。"""
    specs: list[tuple[str, str, dict[str, str], Any, RiskLevel, str]] = [
        (
            "sandbox_create_directory",
            "在任务 worktree 内创建目录",
            {"path": "str"},
            ts.create_directory,
            RiskLevel.SENSITIVE,
            "normal",
        ),
        (
            "sandbox_write_file",
            "在任务 worktree 内创建/覆盖文件（原子写+备份+Artifact）",
            {"path": "str", "content": "str"},
            ts.write_file,
            RiskLevel.SENSITIVE,
            "normal",
        ),
        (
            "sandbox_apply_patch",
            "应用已批准的 PatchProposal（JSON）",
            {"patch_json": "str"},
            ts.apply_patch,
            RiskLevel.SENSITIVE,
            "normal",
        ),
        (
            "sandbox_copy_file",
            "worktree 内复制文件",
            {"source": "str", "destination": "str"},
            ts.copy_file,
            RiskLevel.SENSITIVE,
            "normal",
        ),
        (
            "sandbox_move_file",
            "worktree 内移动文件",
            {"source": "str", "destination": "str"},
            ts.move_file,
            RiskLevel.SENSITIVE,
            "normal",
        ),
        (
            "sandbox_delete_path",
            "删除 worktree 内路径（移入回收区，可恢复）",
            {"path": "str"},
            ts.delete_path,
            RiskLevel.DANGEROUS,
            "destructive",
        ),
        (
            "sandbox_restore_backup",
            "从备份恢复文件",
            {"backup_name": "str", "target": "str"},
            ts.restore_backup,
            RiskLevel.SENSITIVE,
            "normal",
        ),
    ]
    return [
        ToolSpec(
            name=name,
            description=desc,
            input_schema=schema,
            risk_level=risk,
            read_only=False,
            requires_approval=True,  # 网关放行需 ctx.approval_id（M3-C 审批流）
            handler=handler,
            roles=("executor",),
            accepts_ctx=True,  # M3-C：写工具需 ctx（approval_id 绑定）
            permission_risk=permission_risk,
        )
        for name, desc, schema, handler, risk, permission_risk in specs
    ]
