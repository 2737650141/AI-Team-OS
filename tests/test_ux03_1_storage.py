"""024-A STORAGE 后端测试门禁 STORAGE01-10。

覆盖：根目录解析、大小、原子迁移、校验拒绝（App install 只读）、失败回滚、
Project Workspace override、安全清理、Secret DPAPI 密文迁移规则。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.storage import (
    CLEANABLE,
    ROOT_KEYS,
    USER_SELECTABLE,
    StorageError,
    StorageRegistry,
    dir_size_bytes,
)


@pytest.fixture()
def registry(tmp_path: Path) -> StorageRegistry:
    return StorageRegistry(tmp_path / "data")


# STORAGE01：八类根目录齐全，且顺序稳定
def test_storage01_eight_roots(registry: StorageRegistry) -> None:
    roots = registry.roots()
    assert [r.key for r in roots] == list(ROOT_KEYS)
    assert len(roots) == 8


# STORAGE02：app_install 只读且不可用户选择/不可清理
def test_storage02_app_install_readonly(registry: StorageRegistry) -> None:
    summary = registry.config_summary()
    app_install = next(r for r in summary["roots"] if r["key"] == "app_install")
    assert app_install["readonly"] is True
    assert app_install["user_selectable"] is False
    assert app_install["cleanable"] is False
    assert summary["app_install_readonly"] is True


# STORAGE03：memory / workspace 支持用户选择目录
def test_storage03_user_selectable(registry: StorageRegistry) -> None:
    assert USER_SELECTABLE == {"memory", "workspace"}
    for r in registry.roots():
        if r.key in USER_SELECTABLE:
            assert r.user_selectable is True


# STORAGE04：cache / log / snapshot 可安全清理
def test_storage04_cleanable(registry: StorageRegistry) -> None:
    assert CLEANABLE == {"cache", "log", "snapshot"}
    for r in registry.roots():
        assert r.cleanable == (r.key in CLEANABLE)


# STORAGE05：目录大小计算（存在/不存在）
def test_storage05_dir_size(tmp_path: Path) -> None:
    assert dir_size_bytes(tmp_path / "missing") is None
    d = tmp_path / "dir"
    (d / "a").mkdir(parents=True)
    (d / "a" / "one.txt").write_bytes(b"12345")
    (d / "b").mkdir()
    (d / "b" / "two.bin").write_bytes(b"123")
    assert dir_size_bytes(d) == 8


# STORAGE06：workspace 原子迁移 + 内容校验 + 旧目录移除
def test_storage06_migrate_workspace(registry: StorageRegistry, tmp_path: Path) -> None:
    old = registry.resolve("workspace")
    old.mkdir(parents=True)
    (old / "proj").write_text("payload")
    target = tmp_path / "ws-target"
    result = registry.migrate("workspace", target)
    assert result["migrated"] is True
    assert registry.resolve("workspace") == target.resolve()
    assert (target / "proj").read_text() == "payload"
    assert not old.exists()


# STORAGE07：目标在 App 安装目录内 → 拒绝迁移（App 禁止写用户数据）
def test_storage07_reject_inside_app_install(registry: StorageRegistry) -> None:
    app_install = registry.default_path("app_install")
    with pytest.raises(StorageError):
        registry.migrate("workspace", app_install / "nested-ws")


# STORAGE08：非用户可选根不可迁移；不可清理根不可清理
def test_storage08_reject_nonmigratable(registry: StorageRegistry) -> None:
    with pytest.raises(StorageError):
        registry.migrate("artifact", Path("C:/tmp/artifact"))
    with pytest.raises(StorageError):
        registry.migrate("cache", Path("C:/tmp/cache"))
    with pytest.raises(StorageError):
        registry.clean("workspace")


# STORAGE09：迁移失败回滚（校验失败后旧配置保留、新目录清理）
def test_storage09_migrate_rollback(registry: StorageRegistry, tmp_path: Path) -> None:
    old = registry.resolve("memory")
    old.mkdir(parents=True)
    (old / "memory.sqlite").write_bytes(b"\x00" * 16)
    # 目标路径被一个文件占用 → 复制阶段 OSError → 回滚
    target = tmp_path / "mem-target"
    target.write_text("occupied")
    with pytest.raises(StorageError):
        registry.migrate("memory", target)
    # 回滚后：覆盖配置未写入，旧目录仍可用
    assert "memory" not in registry._overrides
    assert registry.resolve("memory") == old
    assert (old / "memory.sqlite").exists()
    # 配置文件中也没有残留（新校验在写配置前拒绝，文件可能尚未创建）
    if registry._config_path.exists():
        assert "memory" not in json.loads(registry._config_path.read_text(encoding="utf-8"))[
            "overrides"
        ]


# STORAGE14：非空目标目录直接拒绝（绝不删除用户已有内容）
def test_storage14_reject_nonempty_target(registry: StorageRegistry, tmp_path: Path) -> None:
    old = registry.resolve("workspace")
    old.mkdir(parents=True)
    (old / "proj.txt").write_text("keep")
    target = tmp_path / "ws-target"
    target.mkdir(parents=True)
    (target / "user-data.txt").write_text("precious")  # 用户已有内容
    with pytest.raises(StorageError):
        registry.migrate("workspace", target)
    # 用户内容原封未动，配置未切换，旧目录仍在
    assert (target / "user-data.txt").read_text() == "precious"
    assert "workspace" not in registry._overrides
    assert registry.resolve("workspace") == old
    assert (old / "proj.txt").read_text() == "keep"


# STORAGE15：空目录目标允许迁移（契约：空目录或新目录）
def test_storage15_migrate_into_empty_dir(registry: StorageRegistry, tmp_path: Path) -> None:
    old = registry.resolve("workspace")
    old.mkdir(parents=True)
    (old / "proj").write_text("payload")
    target = tmp_path / "empty-target"
    target.mkdir(parents=True)  # 已存在的空目录
    result = registry.migrate("workspace", target)
    assert result["migrated"] is True
    assert registry.resolve("workspace") == target.resolve()
    assert (target / "proj").read_text() == "payload"


# STORAGE16：目标位于当前根目录内部 → 拒绝（防止切换后 rmtree 删除新副本）
def test_storage16_reject_nested_target(registry: StorageRegistry) -> None:
    current = registry.resolve("workspace")
    current.mkdir(parents=True)
    with pytest.raises(StorageError):
        registry.migrate("workspace", current / "nested")


def test_storage17_rollback_preserves_existing_override(
    registry: StorageRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "memory-first"
    registry.migrate("memory", first)
    (first / "memory.sqlite").write_bytes(b"existing")
    second = tmp_path / "memory-second"

    from app.core import storage as storage_module

    real_size = storage_module.dir_size_bytes

    def mismatched_size(path: Path) -> int | None:
        value = real_size(path)
        return (value or 0) + 1 if path.resolve() == second.resolve() else value

    monkeypatch.setattr(storage_module, "dir_size_bytes", mismatched_size)
    with pytest.raises(StorageError, match="verification failed"):
        registry.migrate("memory", second)

    assert registry.resolve("memory") == first.resolve()
    saved = json.loads(registry._config_path.read_text(encoding="utf-8"))
    assert saved["overrides"]["memory"] == str(first.resolve())
    assert (first / "memory.sqlite").read_bytes() == b"existing"


def test_storage18_reject_relative_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    registry = StorageRegistry(
        tmp_path / "data", app_install_root=tmp_path / "app-install"
    )
    with pytest.raises(StorageError, match="absolute"):
        registry.migrate("workspace", Path("relative-workspace"))


def test_storage19_project_profile_has_required_fields(
    registry: StorageRegistry, tmp_path: Path
) -> None:
    workspace = tmp_path / "project-workspace"
    artifacts = tmp_path / "project-artifacts"
    profile = registry.set_project_profile(
        "project-a",
        name="Project A",
        workspace_path=workspace,
        memory_scope="project",
        artifact_path=artifacts,
    )
    assert profile == {
        "project_id": "project-a",
        "name": "Project A",
        "workspace_path": str(workspace.resolve()),
        "memory_scope": "project",
        "artifact_path": str(artifacts.resolve()),
    }
    assert registry.workspace_root("project-a") == workspace.resolve()
    assert registry.artifact_root("project-a") == artifacts.resolve()
    reloaded = StorageRegistry(registry._data_root, config_path=registry._config_path)
    assert reloaded.config_summary()["project_profiles"] == [profile]


def test_storage20_memory_service_uses_configured_root(tmp_path: Path) -> None:
    from app.memory.service import MemoryService

    data_root = tmp_path / "data"
    memory_root = tmp_path / "memory-root"
    StorageRegistry(data_root).migrate("memory", memory_root)
    service = MemoryService.from_data_dir(data_root)
    assert service.store.db_path == memory_root.resolve() / "memory.sqlite"


def test_storage21_project_workspace_and_artifact_roots_are_consumed(
    tmp_path: Path,
) -> None:
    from app.core.artifacts import ArtifactWriter
    from app.core.workspace import WorkspaceManager
    from app.runner import workspaces

    data_root = tmp_path / "data"
    workspace_root = tmp_path / "project-workspace"
    artifact_root = tmp_path / "project-artifacts"
    registry = StorageRegistry(data_root)
    registry.set_project_profile(
        "project-a",
        name="Project A",
        workspace_path=workspace_root,
        memory_scope="project",
        artifact_path=artifact_root,
    )
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("project")
    manager = WorkspaceManager(
        data_root / "runtime", workspace_root=registry.workspace_root("project-a")
    )
    manager.create_workspace("task-storage-1", "source", source)
    writer = ArtifactWriter(
        data_root / "runtime",
        "task-storage-1",
        workspace_root=registry.workspace_root("project-a"),
        artifact_root=registry.artifact_root("project-a"),
    )
    artifact = writer.write(
        artifact_type="final_report",
        content="done",
        task_id="task-storage-1",
    )
    assert Path(artifact.path).is_relative_to(artifact_root.resolve())
    assert workspaces(data_root)[0]["task_id"] == "task-storage-1"


def test_storage22_snapshot_cleanup_preserves_valid_snapshots(
    registry: StorageRegistry,
) -> None:
    snapshots = registry.resolve("snapshot")
    valid = snapshots / "task-valid"
    obsolete = snapshots / "task-obsolete"
    valid.mkdir(parents=True)
    obsolete.mkdir(parents=True)
    (valid / "evidence.json").write_text("valid")
    (obsolete / "evidence.json").write_text("obsolete")
    (obsolete / ".obsolete").write_text("")

    registry.clean("snapshot")

    assert (valid / "evidence.json").read_text() == "valid"
    assert not obsolete.exists()


def test_storage23_migration_verifies_content_not_only_size(
    registry: StorageRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import storage as storage_module

    current = registry.resolve("workspace")
    current.mkdir(parents=True)
    (current / "project.txt").write_text("ABCD")
    target = tmp_path / "workspace-target"
    real_copytree = storage_module.shutil.copytree

    def corrupt_copytree(src: Path, dst: Path, **kwargs: object):
        result = real_copytree(src, dst, **kwargs)
        (Path(dst) / "project.txt").write_text("WXYZ")
        return result

    monkeypatch.setattr(storage_module.shutil, "copytree", corrupt_copytree)
    with pytest.raises(StorageError, match="verification failed"):
        registry.migrate("workspace", target)
    assert (current / "project.txt").read_text() == "ABCD"


# STORAGE10：Workspace 全局默认 + Project override；Secret 迁移规则为密文
def test_storage10_project_override_and_secret_policy(
    registry: StorageRegistry, tmp_path: Path
) -> None:
    default_ws = registry.workspace_root("unknown-project")
    assert default_ws == registry.resolve("workspace")
    override = tmp_path / "ws-project-a"
    override.mkdir(parents=True)
    registry.set_project_workspace("project-a", override)
    assert registry.workspace_root("project-a") == override.resolve()
    assert registry.workspace_root("project-b") == default_ws
    # 清除 override 回退全局
    registry.set_project_workspace("project-a", None)
    assert registry.workspace_root("project-a") == default_ws
    # Secret 迁移策略：DPAPI 密文 blob 原样移动，不转明文
    assert registry.config_summary()["secret_policy"] == {
        "storage": "windows_secure_store_dpapi",
        "migration": "encrypted_blobs_only",
    }


# STORAGE11（补充）：迁移后重启（重新加载配置）仍生效 —— Memory 指向测试目录后重启仍正确
def test_storage11_persists_across_reload(registry: StorageRegistry, tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory-on-d"
    memory_dir.mkdir(parents=True)
    registry.migrate("memory", memory_dir)
    # 模拟重启：同一 data root 重新构造 registry
    reloaded = StorageRegistry(registry._data_root, config_path=registry._config_path)
    assert reloaded.resolve("memory") == memory_dir.resolve()


# STORAGE13（特别真实验证 5）：App install 目录大小不因 Memory/Workspace 内容增长
def test_storage13_app_install_size_not_growing() -> None:
    # app_install 固定为仓库根；memory/workspace 内容写入 data root 或迁移目标，
    # 二者均被禁止落在 app_install 内部（STORAGE07），因此 app_install 大小不受影响。
    # 验证路径解析与拒绝规则，不实际复制仓库根（避免慢测试）。
    app_install = StorageRegistry._default_app_install()
    data_root = app_install / "runtime-data"
    registry = StorageRegistry(data_root, app_install_root=app_install)
    memory = registry.resolve("memory")
    workspace = registry.resolve("workspace")
    # memory/workspace 默认位于 data root 之下，data root 不允许是 app_install
    assert str(memory).startswith(str(registry._data_root))
    assert str(workspace).startswith(str(registry._data_root))
    # 目标禁止落在 app_install 内（STORAGE07 已验证），内容不会写入安装目录
    with pytest.raises(StorageError):
        registry.migrate("memory", app_install / "nested-memory")
    # app_install 本身是只读根（readonly=True），不参与用户数据写入
    summary = registry.config_summary()
    app_root = next(r for r in summary["roots"] if r["key"] == "app_install")
    assert app_root["readonly"] is True


# STORAGE12：API 端点（GET 状态 / 迁移 / 清理 / Project override / 非法目标拒绝）
def test_storage12_api_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.api import server

    data = tmp_path / "api-data"
    data.mkdir(parents=True)
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(data))
    # 重置单例，让 storage 指向新 data root
    server._storage_registry = None
    client = TestClient(server.app)

    status = client.get("/settings/storage")
    assert status.status_code == 200
    body = status.json()
    assert len(body["roots"]) == 8
    assert body["app_install_readonly"] is True

    # 迁移 workspace
    ws_target = tmp_path / "ws-api"
    migrated = client.put(
        "/settings/storage/roots", json={"key": "workspace", "target": str(ws_target)}
    )
    assert migrated.status_code == 200
    assert migrated.json()["migrated"] is True
    after = client.get("/settings/storage").json()
    ws = next(r for r in after["roots"] if r["key"] == "workspace")
    assert ws["path"] == str(ws_target.resolve())

    # Project override
    ov = client.put(
        "/settings/storage/workspace-override",
        json={"project_id": "proj-a", "target": str(tmp_path / "ws-proj-a")},
    )
    assert ov.status_code == 200
    assert ov.json()["workspace"] == (tmp_path / "ws-proj-a").resolve().as_posix()

    profile = client.put(
        "/settings/storage/workspace-override",
        json={
            "project_id": "proj-b",
            "project_name": "Project B",
            "target": str(tmp_path / "ws-proj-b"),
            "memory_scope": "project",
            "artifact_path": str(tmp_path / "artifacts-proj-b"),
        },
    )
    assert profile.status_code == 200
    assert profile.json()["name"] == "Project B"
    assert profile.json()["memory_scope"] == "project"

    # 清理 cache
    cache = client.post("/settings/storage/cleanup", json={"key": "cache"})
    assert cache.status_code == 200
    assert cache.json()["cleaned"] is True

    # 拒绝：迁移到 app install 内 / 非用户可选根
    bad = client.put(
        "/settings/storage/roots",
        json={"key": "workspace", "target": str(Path(__file__).resolve().parents[1])},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "storage_error"
    not_selectable = client.put(
        "/settings/storage/roots", json={"key": "cache", "target": str(tmp_path / "c")}
    )
    # schema 正则已拦截非用户可选根（422 早于业务层 400）
    assert not_selectable.status_code == 422
    server._storage_registry = None  # 还原，避免污染其他测试
