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
    assert "reasonix" not in fsck.lower()


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


def test_env_example_placeholder_exempt() -> None:
    """An empty environment-template value is not a secret."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scan_staged_secrets", ROOT / "scripts" / "scan_staged_secrets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert mod.scan_text(text, source_path=".env.example") == []


def test_staged_scan_allows_marked_fixture_and_blocks_real(monkeypatch) -> None:
    """Only marked tests fixtures are exempt; unmarked values remain blocking."""
    import importlib.util

    from app.core.secrets import SECRET_PATTERNS

    spec = importlib.util.spec_from_file_location(
        "scan_staged_secrets", ROOT / "scripts" / "scan_staged_secrets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    test_path = "tests/test_sec01_incident.py"
    placeholder = "AI_TEAM_MODEL_API_KEY=AI_TEAM_OS_TEST_sk-PLACEHOLDER-INCIDENT"
    assert mod.scan_text(placeholder, source_path=test_path) == []
    assert mod.scan_text("token:AI_TEAM_OS_TEST_INCIDENT_TOKEN", source_path=test_path) == []

    real = "AI_TEAM_MODEL_API_KEY=" + "sk-" + "a" * 30
    assert len(mod.scan_text(real, source_path=test_path)) >= 1

    # A comment marker and a variable-name marker do not exempt a value.
    sneaky = 'api_key="' + "sk-" + "b" * 30 + '"  # AI_TEAM_OS_TEST_'
    assert len(mod.scan_text(sneaky, source_path=test_path)) >= 1
    named_marker = "AI_TEAM_OS_TEST_API_KEY=" + "sk-" + "c" * 30
    assert len(mod.scan_text(named_marker, source_path=test_path)) >= 1
    embedded = "sk-" + "a" * 20 + "AI_TEAM_OS_TEST_"
    assert len(mod.scan_text(embedded, source_path=test_path)) >= 1

    report = mod.scan_text('k = "' + "sk-" + "d" * 30 + '"')
    assert report and "d" * 30 not in report[0] and "sha256:" in report[0]

    pem = (
        "AI_TEAM_OS_TEST_"
        + "-----BEGIN "
        + "PRIVATE KEY-----\n"
        + "AI_TEAM_OS_TEST_MOCK_KEY"
        + "A" * 40
        + "\n"
        + "-----END "
        + "PRIVATE KEY-----\n"
    )
    assert mod.scan_text(pem, source_path=test_path) == []
    assert len(mod.scan_text(pem)) == 1

    assert any(p.search("sk-" + "a" * 20) for p in SECRET_PATTERNS)


def test_scan_incident_script_runs() -> None:
    """脱敏定位脚本可运行（clean 时退出 0）。"""
    import sys

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "scan_incident.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0
    assert "(none)" in r.stdout or "no reflog" in r.stdout
    assert "sk-" not in r.stdout  # 不输出凭据原文
