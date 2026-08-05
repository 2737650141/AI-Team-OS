"""审计日志测试：R09/R20（密钥与机密脱敏）。"""

from __future__ import annotations

from pathlib import Path

from app.gateway.audit import AuditLog, redact


def test_redact_secrets() -> None:
    assert "sk-" not in redact("key=sk-abcDEF1234567890xyz")
    assert "***" in redact("key=sk-abcDEF1234567890xyz")
    assert redact("no secrets here") == "no secrets here"
    # security review：补充常见密钥形态
    assert "AKIA" not in redact("aws=AKIA1234567890ABCDEF")
    assert "ghp_" not in redact("gh=ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "sk-" not in redact("header api_key=sk-abcdef1234567890")
    assert "secret" not in redact("db password=supersecretvalue123")
    # PEM 整块（BEGIN+END）整体替换，密钥体不泄露
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAKCAQEAabcdef\n-----END RSA PRIVATE KEY-----"
    assert "MIIEpQIBAAKCAQEAabcdef" not in redact(pem)
    assert "PRIVATE KEY" not in redact(pem)


def test_audit_log_redacts_on_write(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.entry(
        "test_event",
        task_id="t1",
        api_key="sk-abcdef1234567890",
        token="Bearer abcdef.ghijkl.mnopqr",
    )
    # review 复核：走真实写入路径（JSON 序列化带引号）也要脱敏
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAKCAQEAabcdef\n-----END RSA PRIVATE KEY-----"
    audit.entry(
        "test_event2",
        task_id="t1",
        google_key="api_key=AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz012345",
        pem=pem,
    )

    content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "sk-abcdef1234567890" not in content
    assert "abcdef.ghijkl.mnopqr" not in content
    assert content.count("***") >= 4
    # JSON 序列化后无前缀密钥与 PEM 密钥体均不得泄露
    assert "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz012345" not in content
    assert "MIIEpQIBAAKCAQEAabcdef" not in content
    assert "PRIVATE KEY" not in content


def test_audit_entries_append(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.entry("a", task_id="t1")
    audit.entry("b", task_id="t1")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
