"""Tool Gateway 测试：GT-10 M1 拦截 / GT-03 只读 / R19 幂等。"""

from __future__ import annotations

from pathlib import Path

from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext
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


def test_full_access_bypasses_only_approval_gate(tmp_path: Path) -> None:
    from app.tools.spec import RiskLevel, ToolSpec

    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1", approval_bypass=True)
    executed: list[str] = []

    def handler(path: str, content: str) -> dict:
        executed.append(f"{path}:{content}")
        return {"ok": True}

    gateway.register(
        ToolSpec(
            name="full_access_write",
            description="write fixture",
            input_schema={"path": "str", "content": "str"},
            risk_level=RiskLevel.DANGEROUS,
            read_only=False,
            requires_approval=True,
            handler=handler,
        )
    )

    result = gateway.invoke("full_access_write", {"path": "/tmp/x", "content": "ok"})

    assert result.ok is True
    assert executed == ["/tmp/x:ok"]
    assert gateway.approvals == []
    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "tool_approval_bypassed" in audit_text


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
    """R19 + 004 4.1：恢复/重放时同一调用不重复执行，改为缓存复用 cached_success_result。"""
    first = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "crewai"})
    second = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "crewai"})

    assert first.ok is True
    assert second.status == "cached_success_result"
    assert second.ok is True
    assert second.evidence_id == first.evidence_id  # Evidence 复用
    # 两次调用均有记录（原始 ok + 缓存命中 cached_success_result），审计轨迹完整
    assert len(tool_gateway.evidence) == 1


def test_cached_success_does_not_consume_a_second_quota_unit(tool_gateway: ToolGateway) -> None:
    ctx = ToolExecutionContext(
        task_id="t1",
        subtask_id="s1",
        role="researcher",
        tool_call_budget=1,
        replay=True,
    )
    first = tool_gateway.invoke(
        "fixture_repo_lookup", {"repo_name": "langgraph"}, ctx=ctx
    )
    replay = tool_gateway.invoke(
        "fixture_repo_lookup", {"repo_name": "langgraph"}, ctx=ctx
    )

    assert first.ok is True
    assert replay.ok is True
    assert replay.status == "cached_success_result"


def test_read_only_replays_when_restart_cache_is_unavailable(tmp_path: Path) -> None:
    from app.tools.spec import RiskLevel, ToolSpec

    calls: list[str] = []

    def handler(value: str) -> dict:
        calls.append(value)
        return {"value": value}

    spec = ToolSpec(
        name="safe_read",
        description="safe read",
        input_schema={"value": "str"},
        risk_level=RiskLevel.SAFE,
        read_only=True,
        handler=handler,
    )
    audit = AuditLog(tmp_path / "audit.jsonl")
    first_gateway = ToolGateway(audit=audit, task_id="t1")
    first_gateway.register(spec)
    assert first_gateway.invoke("safe_read", {"value": "x"}).ok is True

    resumed_gateway = ToolGateway(
        audit=audit,
        task_id="t1",
        initial_keys=first_gateway.seen_keys,
    )
    resumed_gateway.register(spec)
    replayed = resumed_gateway.invoke("safe_read", {"value": "x"})

    assert replayed.ok is True
    assert replayed.status == "ok"
    assert calls == ["x", "x"]


def test_requires_approval_tool_blocked_even_if_safe(tmp_path: Path) -> None:
    """security review：错标 risk_level=SAFE 但 requires_approval=True 的工具同样被拦截。"""
    from app.tools.spec import RiskLevel, ToolSpec

    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1")
    executed: list[str] = []

    def handler(path: str, content: str) -> dict:
        executed.append(path)
        return {"ok": True}

    gateway.register(
        ToolSpec(
            name="mislabeled_tool",
            description="错标风险的写工具",
            input_schema={"path": "str", "content": "str"},
            risk_level=RiskLevel.SAFE,
            read_only=False,
            requires_approval=True,
            handler=handler,
        )
    )

    result = gateway.invoke("mislabeled_tool", {"path": "/x", "content": "y"})

    assert result.status == "blocked"
    assert executed == []  # handler 未执行
    assert len(gateway.approvals) == 1
    # 审计 reason 明确记录拦截原因（防未来拦截分支回归不可见）
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip().splitlines()
    blocked = [line for line in lines if '"tool_blocked"' in line]
    assert blocked and "dangerous_or_requires_approval_m1" in blocked[-1]


def test_tool_error_recorded(tool_gateway: ToolGateway) -> None:
    """GT-08 基础：工具失败返回 error 且记录。"""
    result = tool_gateway.invoke("fixture_repo_lookup", {"repo_name": "missing_repo"})
    assert result.status == "error"
    assert result.ok is False


def test_non_readonly_tool_blocked_even_if_safe(tmp_path: Path) -> None:
    """安全收紧：非只读工具一律拦截（防错标风险，security_review MEDIUM-3）。"""
    from app.tools.spec import RiskLevel, ToolSpec

    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t1")
    calls: list[str] = []

    def handler(path: str, content: str) -> dict:
        calls.append(path)
        return {"ok": True}

    gateway.register(
        ToolSpec(
            name="safe_write_mislabeled",
            description="演示：safe 但非只读（错标）",
            input_schema={"path": "str", "content": "str"},
            risk_level=RiskLevel.SAFE,  # 错标为 safe
            read_only=False,
            handler=handler,
        )
    )

    result = gateway.invoke("safe_write_mislabeled", {"path": "a", "content": "b"})

    assert result.status == "blocked"
    assert result.ok is False
    assert calls == []  # handler 未执行
    assert gateway.approvals[0]["status"] == "pending"
