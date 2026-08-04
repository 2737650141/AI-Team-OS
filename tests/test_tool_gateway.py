"""Tool Gateway 测试：GT-10 M1 拦截 / GT-03 只读 / R19 幂等。"""

from __future__ import annotations

from pathlib import Path

from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.tools.fixture_repo import DangerousWriteTool


def test_dangerous_tool_blocked_handler_never_runs(tmp_path: Path) -> None:
    """GT-10（M1）：DangerousWriteTool 被确定性拦截，handler 执行次数 = 0。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1")
    dangerous = DangerousWriteTool()
    gateway.register(dangerous.spec())

    result = gateway.invoke("dangerous_write", {"path": "/tmp/x", "content": "boom"})

    assert result.status == "blocked"
    assert result.ok is False
    assert dangerous.exec_count == 0  # handler 永不执行
    assert len(gateway.approvals) == 1
    assert gateway.approvals[0]["status"] == "pending"


def test_safe_readonly_lookup_allowed(tool_gateway: ToolGateway) -> None:
    """GT-01 离线 + GT-03：safe + read_only 自动放行，产出证据。"""
    result = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "langgraph"})

    assert result.ok is True
    assert result.data["license"] == "MIT"
    assert len(tool_gateway.evidence) == 1
    assert len(tool_gateway.tool_calls) == 1


def test_unknown_tool_rejected(tool_gateway: ToolGateway) -> None:
    result = tool_gateway.invoke("no_such_tool", {})
    assert result.status == "error"
    assert result.ok is False


def test_idempotency_skips_duplicate(tool_gateway: ToolGateway) -> None:
    """R19：恢复/重放时同一调用不重复执行。"""
    first = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "crewai"})
    second = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "crewai"})

    assert first.ok is True
    assert second.status == "skipped"
    assert len(tool_gateway.tool_calls) == 1
    assert len(tool_gateway.evidence) == 1


def test_tool_error_recorded(tool_gateway: ToolGateway) -> None:
    """GT-08 基础：工具失败返回 error 且记录。"""
    result = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "missing_repo"})
    assert result.status == "error"
    assert result.ok is False
