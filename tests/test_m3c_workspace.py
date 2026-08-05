"""007 十九：Workspace 测试（1-8）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.workspace import (
    MAX_PROJECT_BYTES,
    WorkspaceError,
    WorkspaceManager,
    WorkspaceManifest,
)


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    root = tmp_path / "sample-python"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# sample\n", encoding="utf-8")
    (root / "secret.env").write_text("API_KEY=sk-realsecret1234567890", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "x").write_text("venv", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "pkg").write_text("n", encoding="utf-8")
    (root / "id_rsa").write_text("private", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[remote] url = https://x", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "out.bin").write_bytes(b"build")
    return root


def _mgr(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(tmp_path / "runtime")


# ---------- 1. 工作区创建 ----------
def test_workspace_created(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    m = mgr.create_workspace("t1", "sample-python", source)
    base = tmp_path / "runtime" / "workspaces" / "t1"
    assert (base / "input").is_dir()
    assert (base / "worktree").is_dir()
    assert (base / "artifacts").is_dir()
    assert (base / "backups").is_dir()
    assert (base / "logs").is_dir()
    assert (base / "manifest.json").is_file()
    assert m.status == "created"


# ---------- 2. 输入复制 ----------
def test_input_copied(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.create_workspace("t1", "sample-python", source)
    wt = tmp_path / "runtime" / "workspaces" / "t1" / "worktree"
    assert (wt / "src" / "main.py").exists()
    assert "return 1" in (wt / "src" / "main.py").read_text(encoding="utf-8")


# ---------- 3. 排除敏感文件 ----------
def test_sensitive_files_excluded(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    m = mgr.create_workspace("t1", "sample-python", source)
    wt = tmp_path / "runtime" / "workspaces" / "t1" / "worktree"
    assert not (wt / "secret.env").exists()
    assert not (wt / ".venv").exists()
    assert not (wt / "node_modules").exists()
    assert not (wt / "id_rsa").exists()
    assert not (wt / ".git" / "config").exists()
    assert not (wt / "build").exists()
    assert any("secret.env" in e for e in m.excluded_paths)


# ---------- 4. 源项目哈希 ----------
def test_source_root_hash_recorded(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    m = mgr.create_workspace("t1", "sample-python", source)
    assert m.source_root_hash  # 64 位 hex
    assert len(m.source_root_hash) == 64


# ---------- 5. 源项目不可变 ----------
def test_source_project_unchanged(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    m = mgr.create_workspace("t1", "sample-python", source)
    assert mgr.verify_source_unchanged(m, source)  # GT-W10
    # 源项目被外部修改 → 检测失败
    (source / "src" / "main.py").write_text("changed", encoding="utf-8")
    assert not mgr.verify_source_unchanged(m, source)


# ---------- 6. WorkspaceManifest ----------
def test_manifest_roundtrip(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    mgr.create_workspace("t1", "sample-python", source)
    loaded = mgr.load_manifest("t1")
    assert isinstance(loaded, WorkspaceManifest)
    assert loaded.task_id == "t1"
    assert loaded.source_project_alias == "sample-python"
    assert loaded.file_count >= 2  # main.py + README.md
    assert loaded.total_bytes > 0


# ---------- 7. 大项目配额 ----------
def test_large_project_quota(tmp_path: Path, source: Path) -> None:
    (source / "big.bin").write_bytes(b"x" * (MAX_PROJECT_BYTES + 1))
    mgr = _mgr(tmp_path)
    with pytest.raises(WorkspaceError, match="exceeds"):
        mgr.create_workspace("t1", "sample-python", source)


# ---------- 8. 符号链接/Junction 处理 ----------
def test_symlink_not_copied_as_link(tmp_path: Path, source: Path) -> None:
    """复制实现用 shutil.copy2（不保留符号链接语义）；Junction 不用于复制。"""
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    try:
        (source / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlink 需要权限，Windows 跳过（Junction 见下）")
    mgr = _mgr(tmp_path)
    mgr.create_workspace("t1", "sample-python", source)
    wt = tmp_path / "runtime" / "workspaces" / "t1" / "worktree"
    # 符号链接不被复制（排除或复制为普通文件，但绝不指向源外部）
    if (wt / "link.txt").exists():
        assert not (wt / "link.txt").is_symlink()


def test_project_alias_validation(tmp_path: Path, source: Path) -> None:
    mgr = _mgr(tmp_path)
    with pytest.raises(WorkspaceError, match="project alias"):
        mgr.resolve_project_alias("../../etc", [tmp_path])
    resolved = mgr.resolve_project_alias("sample-python", [tmp_path])
    assert resolved == source.resolve()
