"""审计日志测试：R09/R20（密钥与机密脱敏）。"""

from __future__ import annotations

from pathlib import Path

from app.gateway.audit import AuditLog, redact


def test_redact_secrets() -> None:
    assert "sk-" not in redact("key=sk-abcDEF1234567890xyz")
    assert "***" in redact("key=sk-abcDEF1234567890xyz")
    assert redact("no secrets here") == "no secrets here"


def test_audit_log_redacts_on_write(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.entry(
        "test_event",
        task_id="t1",
        api_key="sk-abcdef1234567890",
        token="Bearer abcdef.ghijkl.mnopqr",
    )

    content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "sk-abcdef1234567890" not in content
    assert "abcdef.ghijkl.mnopqr" not in content
    assert content.count("***") >= 2


def test_audit_entries_append(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.entry("a", task_id="t1")
    audit.entry("b", task_id="t1")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
