"""006 四：M3-A 遗留 LOW 修复回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.budget import BudgetController, BudgetSnapshot
from app.core.secrets import SECRET_PATTERNS, redact, scan_text
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import ModelGateway


def test_budget_property_readonly_snapshot(tmp_path: Path) -> None:
    """四.1：ModelGateway.budget 返回只读快照，不暴露可变控制器。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(10000, 1.0)
    gw = ModelGateway(provider=object(), budget=budget, audit=audit, task_id="t")  # type: ignore[arg-type]
    snapshot = gw.budget
    assert isinstance(snapshot, BudgetSnapshot)
    assert snapshot.token_budget == 10000
    assert snapshot.cost_budget == 1.0
    assert snapshot.usage == {"tokens": 0.0, "cost": 0.0, "calls": 0.0}
    # 快照不可变：__slots__ 无 setter
    with pytest.raises(AttributeError):
        snapshot.tokens_used = 999  # type: ignore[misc]
    # 快照与控制器解耦：控制器变化不影响已取快照
    budget.record(100, 100, 0.0)
    assert snapshot.usage["tokens"] == 0.0


def test_pkcs8_private_key_scanned() -> None:
    """四.3：PKCS#8 私钥模式（BEGIN PRIVATE KEY）被统一扫描命中。"""
    pkcs8 = (
        "-----BEGIN PRIVATE KEY-----\n"
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQfake\n"
        "-----END PRIVATE KEY-----"
    )
    hits = scan_text(pkcs8)
    assert any("PRIVATE KEY" in h for h in hits)
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQfake" not in redact(pkcs8)


def test_redact_and_scan_share_patterns() -> None:
    """四.4：运行时脱敏与打包扫描共用模式集——脱敏后扫描零命中。"""
    samples = [
        "key=sk-abcdef1234567890xyz",
        "aws=AKIA1234567890ABCDEF",
        "token=Bearer abcdef.ghijkl.mnopqr",
        "gh=ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        'api_key="AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz012345"',
    ]
    for sample in samples:
        assert scan_text(sample), f"样本未被扫描命中: {sample}"
        cleaned = redact(sample)
        assert scan_text(cleaned) == [], f"脱敏后仍有命中: {sample} -> {cleaned}"


def test_secret_patterns_are_shared_registry() -> None:
    """四.4：统一模式集是唯一权威（SECRET_PATTERNS 非空且覆盖核心形态）。"""
    assert SECRET_PATTERNS
    joined = " ".join(p.pattern for p in SECRET_PATTERNS)
    for marker in ("sk-", "ghp_", "AKIA", "aws[_-]?secret", "PRIVATE KEY", "Bearer", "api[_-]?key"):
        assert marker in joined
