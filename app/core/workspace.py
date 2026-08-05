"""沙箱工作区（007 四）：WorkspaceManager + WorkspaceManifest + 输入复制。

- 每个任务独立目录 runtime/workspaces/<task_id>/：
  input/worktree/artifacts/backups/logs/manifest.json。
- input 只读；worktree 是 Executor 唯一可写目录；整个 runtime/ 被 Git 忽略。
- 输入项目复制：安全校验 → 复制到 worktree → 记录源哈希 → 后续只操作副本。
- 禁止直接修改源项目、符号链接/Junction 代替复制。
- 默认排除敏感文件（.env*/.venv/node_modules/dist/build/__pycache__/.git/objects/.git/config/
  *.pem/*.key/credentials*/secrets*）与大型构建产物。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.secrets import SENSITIVE_SUFFIXES

# 默认排除（007 4.2）
EXCLUDED_NAMES = {
    ".env",
    ".venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".idea",
    ".vscode",
    "credentials",
    "secrets",
}
EXCLUDED_PREFIXES = (".env.", "credentials.", "secrets.")
MAX_PROJECT_BYTES = 50 * 1024 * 1024  # 大项目配额（007 19-7）
MAX_PROJECT_FILES = 20000

_REPO_ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_dir(root: Path) -> str:
    """目录内容哈希（稳定排序，含相对路径与文件哈希）。"""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode())
        h.update(b"\x00")
        h.update(_hash_file(p).encode())
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class WorkspaceManifest:
    """007 4.3：任务工作区元数据。"""

    workspace_id: str
    task_id: str
    source_project_alias: str
    source_root_hash: str
    worktree_path: str
    created_at: str
    file_count: int = 0
    total_bytes: int = 0
    excluded_paths: list[str] = field(default_factory=list)
    git_initialized: bool = False
    current_revision: str | None = None
    status: str = "created"  # created | ready | active | completed | rolled_back

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "source_project_alias": self.source_project_alias,
            "source_root_hash": self.source_root_hash,
            "worktree_path": self.worktree_path,
            "created_at": self.created_at,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "excluded_paths": self.excluded_paths,
            "git_initialized": self.git_initialized,
            "current_revision": self.current_revision,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkspaceManifest":
        return cls(**data)


class WorkspaceError(Exception):
    """工作区错误（安全消息）。"""


class WorkspaceManager:
    """沙箱工作区管理（007 4.1/4.2）。"""

    def __init__(self, runtime_dir: Path) -> None:
        self._runtime = runtime_dir
        self._workspaces = runtime_dir / "workspaces"
        self._workspaces.mkdir(parents=True, exist_ok=True)

    def resolve_project_alias(self, alias: str, allowed_roots: list[Path]) -> Path:
        """别名 → 允许项目目录（服务端静态配置，客户端不能传任意路径）。"""
        if not _REPO_ALIAS_RE.match(alias):
            raise WorkspaceError("project alias must match [A-Za-z0-9_-]{1,64}")
        for root in allowed_roots:
            candidate = (root / alias).resolve()
            root_resolved = root.resolve()
            if candidate.is_dir() and (
                str(candidate) == str(root_resolved)
                or str(candidate).startswith(str(root_resolved) + os.sep)
            ):
                return candidate
        raise WorkspaceError(f"project alias not found under allowed roots: {alias}")

    def create_workspace(
        self, task_id: str, source_alias: str, source_root: Path
    ) -> WorkspaceManifest:
        """创建任务工作区（4.2）：复制到 worktree + 源哈希 + manifest。"""
        workspace_id = uuid.uuid4().hex[:16]
        base = self._workspaces / task_id
        if base.exists():
            raise WorkspaceError(f"workspace already exists for task: {task_id}")
        input_dir = base / "input"
        worktree = base / "worktree"
        (base / "artifacts").mkdir(parents=True)
        (base / "backups").mkdir(parents=True)
        (base / "logs").mkdir(parents=True)
        input_dir.mkdir()
        worktree.mkdir()
        # 源哈希（复制前记录，源项目不可变验证用）
        source_hash = _hash_dir(source_root)
        excluded: list[str] = []
        file_count = 0
        total_bytes = 0
        for p in sorted(source_root.rglob("*")):
            rel = p.relative_to(source_root)
            if self._is_excluded(rel, excluded):
                continue
            if p.is_dir():
                continue
            if file_count >= MAX_PROJECT_FILES:
                raise WorkspaceError(f"project exceeds {MAX_PROJECT_FILES} files")
            total_bytes += p.stat().st_size
            if total_bytes > MAX_PROJECT_BYTES:
                raise WorkspaceError(f"project exceeds {MAX_PROJECT_BYTES} bytes")
            # 双份副本：input/（只读初始快照，回滚用）+ worktree/（Executor 唯一可写）
            for dest_root in (input_dir, worktree):
                dest = dest_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
            file_count += 1
        # 输入快照（只读参考）：记录排除清单即可，不重复复制
        manifest = WorkspaceManifest(
            workspace_id=workspace_id,
            task_id=task_id,
            source_project_alias=source_alias,
            source_root_hash=source_hash,
            worktree_path=str(worktree),
            created_at=_now(),
            file_count=file_count,
            total_bytes=total_bytes,
            excluded_paths=excluded,
        )
        self._write_manifest(base, manifest)
        return manifest

    def _is_excluded(self, rel: Path, excluded: list[str]) -> bool:
        parts = rel.parts
        for part in parts:
            if part in EXCLUDED_NAMES:
                excluded.append(rel.as_posix())
                return True
        name = rel.name
        lowered = name.lower()
        if (
            lowered.startswith(EXCLUDED_PREFIXES)
            or lowered.endswith(".env")
            or lowered.startswith(".env")
        ):
            excluded.append(rel.as_posix())
            return True
        if lowered in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
            excluded.append(rel.as_posix())
            return True
        if rel.suffix.lower() in SENSITIVE_SUFFIXES:
            excluded.append(rel.as_posix())
            return True
        # .git 内部敏感文件（config/objects）
        if ".git" in parts and (rel.name in ("config", "objects") or "objects" in parts):
            excluded.append(rel.as_posix())
            return True
        return False

    def load_manifest(self, task_id: str) -> WorkspaceManifest:
        base = self._workspaces / task_id
        manifest_path = base / "manifest.json"
        if not manifest_path.exists():
            raise WorkspaceError(f"workspace not found for task: {task_id}")
        import json

        return WorkspaceManifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))

    def save_manifest(self, manifest: WorkspaceManifest) -> None:
        base = self._workspaces / manifest.task_id
        self._write_manifest(base, manifest)

    def _write_manifest(self, base: Path, manifest: WorkspaceManifest) -> None:
        import json

        (base / "manifest.json").write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def worktree(self, task_id: str) -> Path:
        return self._workspaces / task_id / "worktree"

    def verify_source_unchanged(self, manifest: WorkspaceManifest, source_root: Path) -> bool:
        """GT-W10：源项目保护验证（哈希比对）。"""
        return _hash_dir(source_root) == manifest.source_root_hash

    def workspaces(self) -> list[dict[str, Any]]:
        """列出全部工作区（manifest 摘要）。"""
        result = []
        for base in sorted(self._workspaces.iterdir()):
            manifest_path = base / "manifest.json"
            if manifest_path.exists():
                import json

                result.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        return result
