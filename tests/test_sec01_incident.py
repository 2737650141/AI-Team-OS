"""SEC-01 Incident 回归测试（008 2.7-10 / 2.5）。

断言仓库不再包含 reasonix.toml 及其凭据：
- 路径与 blob 均不存在（git log --all / fsck 扫描）。
- 工作树无物理残留。
- .gitignore 覆盖 reasonix.toml/.reasonix/.env*。
- 提交前秘密扫描脚本可用（staged 含测试前缀密钥可放行、含真实模式阻塞）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAKED_BLOB = "7f5ddf95028966eba8b35de0a1f3e3f8c05b0e6b"  # SECURITY_INCIDENT_001 记录


def _git(*args: str) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (r.stdout or "") + (r.stderr or "")


def test_no_reasonix_toml_in_history() -> None:
    """任何分支历史都不再包含 reasonix.toml（008 2.5）。"""
    out = _git("log", "--all", "--oneline", "--", "reasonix.toml")
    assert out.strip() == ""


def test_no_leaked_blob_in_object_db() -> None:
    """泄漏 blob 从对象库移除（fsck --full --no-reflogs 无引用、无悬空）。"""
    fsck = _git("fsck", "--full", "--no-reflogs")
    assert LEAKED_BLOB not in fsck
    assert "unreachable" not in fsck.lower() or "reasonix" not in fsck.lower()


def test_no_reflog_reference() -> None:
    """reflog 不再引用泄漏提交（008 2.5）。"""
    reflog = _git("reflog", "--all")
    assert "reasonix" not in reflog.lower()


def test_no_physical_file() -> None:
    """工作树与 .reasonix 无 reasonix.toml 物理文件。"""
    assert not (ROOT / "reasonix.toml").exists()
    if (ROOT / ".reasonix").exists():
        assert not list((ROOT / ".reasonix").rglob("reasonix.toml"))


def test_gitignore_covers_secrets() -> None:
    """防复发 2.7-1：reasonix.toml / .reasonix / .env* 默认忽略。"""
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "reasonix.toml" in gi
    assert ".reasonix/" in gi
    assert ".env" in gi


def test_staged_scan_allows_placeholder_and_blocks_real(monkeypatch) -> None:
    """防复发 2.7-2/2.7-6：提交前扫描——测试前缀（SK-PLACEHOLDER）放行、真实模式阻塞。"""
    import importlib.util

    from app.core.secrets import SECRET_PATTERNS

    spec = importlib.util.spec_from_file_location(
        "scan_staged_secrets", ROOT / "scripts" / "scan_staged_secrets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    placeholder = "AI_TEAM_MODEL_API_KEY=SK-PLACEHOLDER-1234567890"
    real = "AI_TEAM_MODEL_API_KEY=" + "sk-" + "a" * 30  # 拼接避免完整假密钥入 staged diff
    # 测试前缀豁免 → 放行
    assert mod.scan_text(placeholder) == []
    # 真实 sk- 命中 → 阻塞
    assert len(mod.scan_text(real)) >= 1
    # SECRET_PATTERNS 本身（运行时脱敏）仍覆盖 sk- 假密钥（防御纵深）
    assert any(p.search("sk-" + "a" * 20) for p in SECRET_PATTERNS)


def test_scan_incident_script_runs() -> None:
    """脱敏定位脚本可运行（clean 时退出 0）。"""
    r = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python"), str(ROOT / "scripts" / "scan_incident.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0
    assert "(none)" in r.stdout or "no reflog" in r.stdout
    assert "sk-" not in r.stdout  # 不输出凭据原文
