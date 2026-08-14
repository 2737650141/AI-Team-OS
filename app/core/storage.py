"""Storage & Workspace 路径注册表（024-A）。

分离 8 类根目录，全部由 StorageRegistry 统一解析与校验：

- app_install : 应用安装目录（只读，禁止写入任何用户数据）
- data        : 数据根（runtime/ 的父目录，SQLite/checkpoint/audit 所在）
- memory      : Memory SQLite 所在目录
- workspace   : 沙箱工作区根（runtime/workspaces）
- artifact    : Artifact 索引目录（runtime/artifacts）
- snapshot    : Evidence 快照目录（runtime/evidence）
- cache       : 可安全清理的缓存目录
- log         : 运行日志目录

规则：
- App 安装目录禁止写用户数据：app_install 只读，任何迁移目标/数据根
  都不得落在安装目录内部；安装目录本身不参与大小统计写入。
- Memory / Workspace 支持用户选择目录（storage.json 覆盖）。
- Workspace 支持全局默认 + Project override（project_id → 目录）。
- 路径修改必须原子迁移、校验、失败回滚（migrate）。
- 显示各目录当前大小（size_bytes）。
- Cache / Logs / Snapshots 支持安全清理（仅删除各自目录内的内容，
  不触碰 SQLite/凭据/工作区/记忆）。
- 禁止把 Secret 迁移成明文：迁移只移动目录树，不读取/重写
  runtime/secrets 的 DPAPI 密文文件；DPAPI 规则保持不变。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---- 根目录键（稳定顺序，UI 显示用） ----
ROOT_KEYS = (
    "app_install",
    "data",
    "memory",
    "workspace",
    "artifact",
    "snapshot",
    "cache",
    "log",
)

# 可被用户选择目录的根（memory / workspace 支持用户选择目录）
USER_SELECTABLE = {"memory", "workspace"}
# 可安全清理的根
CLEANABLE = {"cache", "log", "snapshot"}

# 默认目录名（相对 data root）
_DEFAULT_SUBDIRS = {
    "memory": "runtime/memory",
    "workspace": "runtime/workspaces",
    "artifact": "runtime/artifacts",
    "snapshot": "runtime/evidence",
    "cache": "runtime/cache",
    "log": "runtime/logs",
}

_CONFIG_NAME = "storage.json"


class StorageError(Exception):
    """存储配置错误（安全消息）。"""


@dataclass
class StorageRoot:
    """单个根目录的解析结果（含大小）。"""

    key: str
    path: str
    default_path: str
    exists: bool
    size_bytes: int | None
    user_selectable: bool
    cleanable: bool
    readonly: bool = False  # app_install 只读

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "default_path": self.default_path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "user_selectable": self.user_selectable,
            "cleanable": self.cleanable,
            "readonly": self.readonly,
        }


def dir_size_bytes(path: Path) -> int | None:
    """目录总大小（递归）；路径不存在返回 None；只统计普通文件。"""
    if not path.exists():
        return None
    total = 0
    for root, dirs, files in os.walk(path):
        # 跳过符号链接目录（防循环）
        dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
        for name in files:
            fp = Path(root) / name
            if fp.is_symlink():
                continue
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def _dir_manifest(path: Path) -> dict[str, tuple[int, str]]:
    if not path.exists():
        return {}
    manifest: dict[str, tuple[int, str]] = {}
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file() or file_path.is_symlink():
            continue
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest[file_path.relative_to(path).as_posix()] = (
            file_path.stat().st_size,
            digest.hexdigest(),
        )
    return manifest


class StorageRegistry:
    """集中路径注册表：解析根目录、原子迁移、安全清理。"""

    def __init__(
        self,
        data_root: Path,
        app_install_root: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._data_root = data_root.resolve()
        self._app_install = (app_install_root or self._default_app_install()).resolve()
        self._config_path = config_path or self._data_root / "runtime" / _CONFIG_NAME
        self._lock = threading.RLock()
        self._overrides: dict[str, str] = {}  # root_key -> absolute path
        self._project_workspace_overrides: dict[str, str] = {}  # project_id -> path
        self._project_profiles: dict[str, dict[str, str]] = {}
        self._load()

    # ---- 默认值 ----
    @staticmethod
    def _default_app_install() -> Path:
        # PyInstaller 单文件模式使用 _MEIPASS；开发模式用仓库根（AI Team OS 源码目录）
        meipass = getattr(__import__("sys"), "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        # app/core/storage.py → parents[2] = 仓库根（含 app/ 与 web/）
        return Path(__file__).resolve().parents[2]

    def default_path(self, key: str) -> Path:
        if key == "app_install":
            return self._app_install
        if key == "data":
            return self._data_root
        sub = _DEFAULT_SUBDIRS.get(key)
        if sub is None:
            raise StorageError(f"unknown storage root: {key}")
        return self._data_root / sub

    # ---- 解析 ----
    def resolve(self, key: str) -> Path:
        """返回根目录的当前路径（覆盖优先，否则默认）。"""
        if key not in ROOT_KEYS:
            raise StorageError(f"unknown storage root: {key}")
        with self._lock:
            override = self._overrides.get(key)
        if override:
            return Path(override)
        return self.default_path(key)

    def workspace_root(self, project_id: str | None = None) -> Path:
        """Workspace 根：Project override 优先，其次全局默认 Workspace。"""
        with self._lock:
            profile = self._project_profiles.get(project_id or "")
            if profile and profile.get("workspace_path"):
                return Path(profile["workspace_path"])
            if project_id and project_id in self._project_workspace_overrides:
                return Path(self._project_workspace_overrides[project_id])
        return self.resolve("workspace")

    def artifact_root(self, project_id: str | None = None) -> Path:
        with self._lock:
            profile = self._project_profiles.get(project_id or "")
            if profile and profile.get("artifact_path"):
                return Path(profile["artifact_path"])
        return self.resolve("artifact")

    def roots(self) -> list[StorageRoot]:
        """全部根目录状态（含大小）。"""
        result: list[StorageRoot] = []
        for key in ROOT_KEYS:
            path = self.resolve(key)
            result.append(
                StorageRoot(
                    key=key,
                    path=str(path),
                    default_path=str(self.default_path(key)),
                    exists=path.exists(),
                    size_bytes=dir_size_bytes(path),
                    user_selectable=key in USER_SELECTABLE,
                    cleanable=key in CLEANABLE,
                    readonly=(key == "app_install"),
                )
            )
        return result

    def config_summary(self) -> dict[str, Any]:
        """API 视图：roots + workspace 覆盖 + secret 规则状态。"""
        return {
            "roots": [r.to_dict() for r in self.roots()],
            "project_workspace_overrides": dict(self._project_workspace_overrides),
            "project_profiles": list(self._project_profiles.values()),
            "secret_policy": {
                "storage": "windows_secure_store_dpapi",
                "migration": "encrypted_blobs_only",  # 迁移只移动密文，不转明文
            },
            "app_install_readonly": True,
        }

    def project_profiles(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(profile) for profile in self._project_profiles.values()]

    # ---- 持久化 ----
    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # 损坏配置忽略，回退默认（不阻塞启动）
        overrides = data.get("overrides") or {}
        for key, value in overrides.items():
            if key in USER_SELECTABLE and isinstance(value, str):
                self._overrides[key] = value
        self._project_workspace_overrides = {
            str(k): str(v)
            for k, v in (data.get("project_workspace_overrides") or {}).items()
            if isinstance(v, str)
        }
        self._project_profiles = {
            str(item["project_id"]): {
                "project_id": str(item["project_id"]),
                "name": str(item.get("name") or item["project_id"]),
                "workspace_path": str(item.get("workspace_path") or ""),
                "memory_scope": str(item.get("memory_scope") or "project"),
                "artifact_path": str(item.get("artifact_path") or ""),
            }
            for item in (data.get("project_profiles") or [])
            if isinstance(item, dict) and item.get("project_id")
        }
        for project_id, path in self._project_workspace_overrides.items():
            self._project_profiles.setdefault(
                project_id,
                {
                    "project_id": project_id,
                    "name": project_id,
                    "workspace_path": path,
                    "memory_scope": "project",
                    "artifact_path": "",
                },
            )

    def _save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "overrides": dict(self._overrides),
            "project_workspace_overrides": dict(self._project_workspace_overrides),
            "project_profiles": list(self._project_profiles.values()),
        }
        tmp = self._config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._config_path)

    # ---- 校验 ----
    @staticmethod
    def _validate_target(key: str, target: Path, app_install: Path) -> None:
        if key not in USER_SELECTABLE:
            raise StorageError(f"root is not user-selectable: {key}")
        if not target.is_absolute():
            raise StorageError("storage path must be absolute")
        resolved = target.resolve()
        # 空/相对路径不允许
        if not str(resolved):
            raise StorageError("storage path must be absolute")
        # App 安装目录禁止写用户数据：目标不得位于安装目录内部（Windows 大小写不敏感）
        app_resolved = app_install.resolve()
        resolved_text = str(resolved)
        app_text = str(app_resolved)
        if os.name == "nt":
            resolved_text = resolved_text.lower()
            app_text = app_text.lower()
        if resolved_text == app_text or resolved_text.startswith(app_text + os.sep):
            raise StorageError("storage path must not be inside the app install directory")
        # 不允许指向系统敏感位置（简易防护：不落盘到 Windows 目录本身）
        if os.name == "nt":
            lowered = str(resolved).lower()
            for system_root in (r"c:\windows", r"c:\program files"):
                if lowered == system_root or lowered.startswith(system_root + os.sep):
                    raise StorageError("storage path must not be a system directory")

    # ---- 原子迁移 ----
    def migrate(self, key: str, target: Path) -> dict[str, Any]:
        """把根目录原子迁移到 target：校验 → 复制 → 校验 → 切换 → 失败回滚。

        迁移只复制目录树（含 DPAPI 密文 blob 原样移动，绝不读取/解密），
        因此不产生任何明文 Secret；旧目录在切换成功后删除。

        安全：目标目录必须是空目录或尚不存在。非空目标直接拒绝，
        绝不删除用户已有的目录内容（回滚只清理本次迁移创建的目标）。
        """
        with self._lock:
            self._validate_target(key, target, self._app_install)
            current = self.resolve(key)
            resolved = target.resolve()
            if current == resolved:
                raise StorageError("target path is already in use")
            # 目标已存在且非空 → 拒绝，避免覆盖用户数据；目标是文件也拒绝
            if resolved.exists() and not resolved.is_dir():
                raise StorageError("target path already exists and is not a directory")
            if resolved.is_dir() and any(resolved.iterdir()):
                raise StorageError(
                    "target directory is not empty; choose an empty or new directory"
                )
            # 目标不得位于当前根目录内部：否则切换成功后 rmtree(current)
            # 会连带删除刚复制的新副本（循环嵌套）
            if str(resolved).startswith(str(current) + os.sep):
                raise StorageError("target path must not be inside the current root directory")
            target_created = not resolved.exists()
            previous_override = self._overrides.get(key)
            current_manifest = _dir_manifest(current)

            def _restore() -> None:
                # 回滚：只删除本次迁移创建的目标目录；配置尚未切换，旧目录保持原状。
                # 若目标在我们创建前已存在（空目录），恢复为删除我们写入的内容。
                if target_created and resolved.exists():
                    shutil.rmtree(resolved, ignore_errors=True)
                elif not target_created and resolved.exists():
                    for child in resolved.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child, ignore_errors=True)
                        else:
                            child.unlink(missing_ok=True)
                if previous_override is None:
                    self._overrides.pop(key, None)
                else:
                    self._overrides[key] = previous_override
                self._save()

            try:
                # 1) 目标父目录就绪
                resolved.parent.mkdir(parents=True, exist_ok=True)
                # 2) 复制（旧目录可能不存在 → 空目标；目标为空目录时允许写入）
                if current.exists():
                    shutil.copytree(current, resolved, symlinks=False, dirs_exist_ok=True)
                else:
                    resolved.mkdir(parents=True, exist_ok=True)
                # 3) 校验复制完整性（文件计数 + 总字节）
                current_size = dir_size_bytes(current) or 0
                new_size = dir_size_bytes(resolved) or 0
                if current.exists() and (
                    current_size != new_size or current_manifest != _dir_manifest(resolved)
                ):
                    _restore()
                    raise StorageError("migration verification failed: size mismatch")
                # 4) 切换配置
                self._overrides[key] = str(resolved)
                self._save()
                # 5) 成功后删除旧目录
                if current.exists() and str(current) != str(resolved):
                    shutil.rmtree(current, ignore_errors=True)
                return {
                    "key": key,
                    "migrated": True,
                    "from": str(current),
                    "to": str(resolved),
                    "size_bytes": new_size,
                }
            except OSError as exc:
                _restore()
                raise StorageError(f"migration failed: {exc}") from exc

    # ---- 安全清理 ----
    def clean(self, key: str) -> dict[str, Any]:
        """安全清理可清理根目录内容（cache/log/snapshot）。"""
        if key not in CLEANABLE:
            raise StorageError(f"root is not cleanable: {key}")
        with self._lock:
            path = self.resolve(key)
            if not path.exists():
                return {"key": key, "cleaned": True, "removed_bytes": 0}
            children = list(path.iterdir())
            if key == "snapshot":
                children = [
                    child
                    for child in children
                    if (child.is_dir() and (child / ".obsolete").exists())
                    or (child.is_file() and child.name.endswith(".obsolete"))
                ]
            removed_bytes = sum(
                (dir_size_bytes(child) or 0) if child.is_dir() else child.stat().st_size
                for child in children
            )
            for child in children:
                if child.is_symlink():
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            return {"key": key, "cleaned": True, "removed_bytes": removed_bytes}

    # ---- Workspace Project override ----
    def set_project_workspace(
        self, project_id: str, target: Path | None
    ) -> dict[str, Any]:
        """设置/清除某个 Project 的 Workspace override（不迁移，仅路由）。"""
        if not project_id or not project_id.strip():
            raise StorageError("project_id is required")
        with self._lock:
            if target is None:
                self._project_workspace_overrides.pop(project_id, None)
                self._project_profiles.pop(project_id, None)
            else:
                self._validate_target("workspace", target, self._app_install)
                self._project_workspace_overrides[project_id] = str(target.resolve())
                if project_id in self._project_profiles:
                    self._project_profiles[project_id]["workspace_path"] = str(
                        target.resolve()
                    )
            self._save()
        return {"project_id": project_id, "workspace": self.workspace_root(project_id).as_posix()}

    def set_project_profile(
        self,
        project_id: str,
        *,
        name: str,
        workspace_path: Path,
        memory_scope: str,
        artifact_path: Path,
    ) -> dict[str, str]:
        if not project_id.strip() or not name.strip():
            raise StorageError("project_id and project name are required")
        if memory_scope not in {"project", "global"}:
            raise StorageError("memory_scope must be project or global")
        self._validate_target("workspace", workspace_path, self._app_install)
        self._validate_target("workspace", artifact_path, self._app_install)
        profile = {
            "project_id": project_id.strip(),
            "name": name.strip(),
            "workspace_path": str(workspace_path.resolve()),
            "memory_scope": memory_scope,
            "artifact_path": str(artifact_path.resolve()),
        }
        with self._lock:
            self._project_profiles[profile["project_id"]] = profile
            self._project_workspace_overrides[profile["project_id"]] = profile[
                "workspace_path"
            ]
            self._save()
        return profile

    def remove_project_profile(self, project_id: str) -> None:
        with self._lock:
            self._project_profiles.pop(project_id, None)
            self._project_workspace_overrides.pop(project_id, None)
            self._save()
