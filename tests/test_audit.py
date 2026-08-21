"""审计日志测试：R09/R20（密钥与机密脱敏）。"""

from __future__ import annotations

from pathlib import Path

from app.gateway.audit import AuditLog, redact


def test_redact_secrets() -> None:
    sk_fixture = "AI_TEAM_OS_TEST_sk-PLACEHOLDER-AUDIT-KEY"
    aws_fixture = "AI_TEAM_OS_TEST_" + "AK" + "IA" + "MOCK" + "A" * 12
    github_fixture = "AI_TEAM_OS_TEST_" + "gh" + "p_" + "MOCK" + "A" * 20
    bearer_fixture = "Bearer AI_TEAM_OS_TEST_AUDIT_BEARER"
    password_fixture = "AI_TEAM_OS_TEST_AUDIT_PASSWORD"

    assert "sk-" not in redact("key=" + sk_fixture)
    assert "***" in redact("key=" + sk_fixture)
    assert redact("no secrets here") == "no secrets here"
    assert "AKIA" not in redact("aws=" + aws_fixture)
    assert "ghp_" not in redact("gh=" + github_fixture)
    assert "sk-" not in redact("header api_key=" + sk_fixture)
    assert "secret" not in redact("db password=" + password_fixture)
    assert "Bearer" not in redact(bearer_fixture)

    pem = (
        "-----BEGIN " + "PRIVATE KEY-----\n"
        + "AI_TEAM_OS_TEST_MOCK_PRIVATE_KEY_MATERIAL\n"
        + "-----END " + "PRIVATE KEY-----"
    )
    assert "AI_TEAM_OS_TEST_MOCK_PRIVATE_KEY_MATERIAL" not in redact(pem)
    assert "PRIVATE KEY" not in redact(pem)
def test_audit_log_redacts_on_write(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    api_key_fixture = "AI_TEAM_OS_TEST_sk-PLACEHOLDER-AUDIT-LOG"
    token_fixture = "Bearer AI_TEAM_OS_TEST_AUDIT_LOG"
    audit.entry(
        "test_event",
        task_id="t1",
        **{"api" + "_key": api_key_fixture, "token": token_fixture},
    )
    pem = (
        "-----BEGIN " + "PRIVATE KEY-----\n"
        + "AI_TEAM_OS_TEST_MOCK_PRIVATE_KEY_MATERIAL\n"
        + "-----END " + "PRIVATE KEY-----"
    )
    audit.entry(
        "test_event2",
        task_id="t1",
        google_key="api_key=" + api_key_fixture,
        pem=pem,
    )

    content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert api_key_fixture not in content
    assert token_fixture not in content
    assert "AI_TEAM_OS_TEST_MOCK_PRIVATE_KEY_MATERIAL" not in content
    assert content.count("***") >= 4
    assert "PRIVATE KEY" not in content
def test_audit_entries_append(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    audit.entry("a", task_id="t1")
    audit.entry("b", task_id="t1")
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
