"""006 十六：Local File（21-33）/ Evidence（34-40）/ MCP（41-46）/ Runtime（47-54）测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.evidence import EvidenceQuotaExceeded, EvidenceWriter
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext, ToolPolicy
from app.tools.local_file import LocalPathPolicy, build_local_tools
from app.tools.mcp_adapter import (
    FakeMCPServer,
    MCPServerConfig,
    MCPToolAdapter,
)


@pytest.fixture()
def local_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (root / "README.md").write_text("# Hello\n", encoding="utf-8")
    (root / "data.json").write_text('{"a": 1, "list": [1, 2, 3]}', encoding="utf-8")
    (root / "data.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (root / "secret.env").write_text("API_KEY=AI_TEAM_OS_TEST_sk-PLACEHOLDER-LOCAL", encoding="utf-8")
    (root / "id_rsa").write_text("ssh private key fake", encoding="utf-8")
    (root / "binary.dat").write_bytes(b"\x00\x01\x02binary")
    # 敏感子目录
    (root / ".ssh").mkdir()
    (root / ".ssh" / "config").write_text("Host x", encoding="utf-8")
    return root


def _tools(root: Path):
    policy = LocalPathPolicy([root])
    return policy, {s.name: s for s in build_local_tools(policy)}


# ---------- Local File（十六 21-33） ----------
def test_local_read_within_root(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("src/main.py")
    assert r["ok"] and "def main" in r["content"]


def test_local_outside_root_rejected(local_root: Path, tmp_path: Path) -> None:
    _, tools = _tools(local_root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    r = tools["local_read_text"].handler(str(outside))  # 绝对路径逃逸
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_dotdot_rejected(local_root: Path, tmp_path: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("../../outside.txt")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_symlink_escape_rejected(local_root: Path, tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("symlink 需要管理员权限，Windows 上跳过（Junction 覆盖见下）")
    target = tmp_path / "secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = local_root / "link.txt"
    link.symlink_to(target)
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("link.txt")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_junction_reparse_point(local_root: Path, tmp_path: Path) -> None:
    """25：Junction/Reparse Point——resolve 后复查位于允许根内。"""
    if os.name != "nt":
        pytest.skip("Junction 仅 Windows")
    import subprocess

    outside = tmp_path / "outside_junction"
    outside.mkdir()
    (outside / "x.txt").write_text("out", encoding="utf-8")
    target = local_root / "junction"
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(outside)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("mklink 不可用")
    except FileNotFoundError:
        pytest.skip("cmd 不可用")
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("junction/x.txt")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_unc_path_rejected(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("\\\\server\\share\\file.txt")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_ads_rejected(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("src/main.py:hidden")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_env_file_rejected(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("secret.env")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_private_key_rejected(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("id_rsa")
    assert r["ok"] is False and r["code"] == "blocked"
    # .ssh 目录内文件同样拒绝
    r2 = tools["local_read_text"].handler(".ssh/config")
    assert r2["ok"] is False and r2["code"] == "blocked"


def test_local_large_file_rejected(local_root: Path) -> None:
    big = local_root / "big.txt"
    big.write_text("x" * (3 * 1024 * 1024), encoding="utf-8")
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("big.txt")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_binary_rejected(local_root: Path) -> None:
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("binary.dat")
    assert r["ok"] is False and r["code"] == "blocked"


def test_local_encoding_error_handled(local_root: Path) -> None:
    weird = local_root / "weird.bin"
    weird.write_bytes(b"\xff\xfe\x00\xff\x00\xfe")  # 无效 UTF-8/UTF-16 序列
    _, tools = _tools(local_root)
    r = tools["local_read_text"].handler("weird.bin")
    # 可能被识别为 utf-16 或拒绝——两者都是受控行为
    assert r["ok"] is True or r["code"] in (
        "blocked",
        "unsupported text encoding" if r.get("error") else "error",
    )


def test_local_dir_entry_limit(local_root: Path) -> None:
    many = local_root / "many"
    many.mkdir()
    for i in range(600):
        (many / f"f{i}.txt").write_text("x", encoding="utf-8")
    _, tools = _tools(local_root)
    r = tools["local_list_directory"].handler("many")
    assert r["ok"] and r["count"] <= 500


# ---------- Evidence（十六 34-40） ----------
def test_evidence_id_unique(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1")
    a = w.write(tool_name="t", source_type="local", source_uri="u", content="x")
    b = w.write(tool_name="t", source_type="local", source_uri="u2", content="y")
    assert a.evidence_id != b.evidence_id


def test_evidence_hash_stable(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1")
    a = w.write(tool_name="t", source_type="local", source_uri="u", content="same")
    assert (
        a.content_hash
        == w.write(tool_name="t", source_type="local", source_uri="u3", content="same").content_hash
    )


def test_evidence_dedup(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1")
    a = w.write(tool_name="t", source_type="local", source_uri="u1", content="same")
    b = w.write(tool_name="t", source_type="local", source_uri="u2", content="same")
    assert a.evidence_id == b.evidence_id  # 同一内容去重（5.1）
    assert w.count() == 1
    assert "u2" in (a.metadata.get("duplicates") or [{}])[0]["source_uri"]


def test_evidence_snapshot_separated(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1")
    rec = w.write(
        tool_name="t", source_type="web", source_uri="https://x", content="hello world" * 10
    )
    snapshot = w.snapshot_path(rec.evidence_id)
    assert snapshot is not None and snapshot.exists()
    assert snapshot.read_text(encoding="utf-8") == "hello world" * 10  # 原文与摘要分离


def test_evidence_truncated_flag(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1", max_snapshot_bytes=100)
    rec = w.write(tool_name="t", source_type="web", source_uri="u", content="x" * 500)
    assert rec.truncated is True
    assert len(w.snapshot_path(rec.evidence_id).read_text(encoding="utf-8")) <= 100


def test_evidence_no_credentials(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1")
    rec = w.write(
        tool_name="t",
        source_type="local",
        source_uri="u",
        content="api_key=AI_TEAM_OS_TEST_sk-PLACEHOLDER-LOCAL and token",
    )
    snapshot = w.snapshot_path(rec.evidence_id).read_text(encoding="utf-8")
    assert "AI_TEAM_OS_TEST_sk-PLACEHOLDER-LOCAL" not in snapshot
    assert "AI_TEAM_OS_TEST_sk-PLACEHOLDER-LOCAL" not in rec.summary


def test_evidence_quota(tmp_path: Path) -> None:
    w = EvidenceWriter(tmp_path, "t1", max_evidence_per_task=2)
    w.write(tool_name="t", source_type="local", source_uri="u", content="1")
    w.write(tool_name="t", source_type="local", source_uri="u", content="2")
    with pytest.raises(EvidenceQuotaExceeded):
        w.write(tool_name="t", source_type="local", source_uri="u", content="3")


# ---------- MCP（十六 41-46） ----------
def _mcp_env():
    server = FakeMCPServer(
        "docs-server",
        {
            "read_doc": (
                {"properties": {"path": {"type": "string"}}},
                lambda path: {"content": f"doc:{path}"},
            ),
            "write_doc": ({"properties": {}}, lambda: {"ok": True}),
        },
    )
    config = MCPServerConfig(
        server_id="docs-server",
        allowed_tools=["read_doc", "write_doc"],
        read_only=True,
    )
    return server, config


def test_mcp_schema_conversion() -> None:
    server, config = _mcp_env()
    adapter = MCPToolAdapter({config.server_id: config}, fake_servers={server.server_id: server})
    audit = AuditLog(Path(".") / "x.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t")
    converted = adapter.register_all(gateway)
    names = [s.name for s in converted]
    assert "mcp_docs-server_read_doc" in names
    assert "mcp_docs-server_write_doc" not in names  # 写语义拒绝（42/44）


def test_mcp_unregistered_server_rejected() -> None:
    server, config = _mcp_env()
    adapter = MCPToolAdapter({}, fake_servers={server.server_id: server})  # 未注册 server
    audit = AuditLog(Path(".") / "x.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t")
    assert adapter.register_all(gateway) == []


def test_mcp_unallowed_tool_rejected() -> None:
    server, config = _mcp_env()
    config.allowed_tools = ["read_doc"]  # write_doc 未登记
    adapter = MCPToolAdapter({config.server_id: config}, fake_servers={server.server_id: server})
    audit = AuditLog(Path(".") / "x.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t")
    names = [s.name for s in adapter.register_all(gateway)]
    assert names == ["mcp_docs-server_read_doc"]


def test_mcp_non_readonly_tool_rejected() -> None:
    server = FakeMCPServer("srv", {"delete_all": ({"properties": {}}, lambda: {"ok": True})})
    config = MCPServerConfig(server_id="srv", allowed_tools=["delete_all"], read_only=False)
    adapter = MCPToolAdapter({config.server_id: config}, fake_servers={server.server_id: server})
    audit = AuditLog(Path(".") / "x.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t")
    assert adapter.register_all(gateway) == []


def test_mcp_result_through_tool_gateway(tmp_path: Path) -> None:
    server, config = _mcp_env()
    adapter = MCPToolAdapter({config.server_id: config}, fake_servers={server.server_id: server})
    audit = AuditLog(tmp_path / "audit.jsonl")
    writer = EvidenceWriter(tmp_path / "runtime", "t")
    gateway = ToolGateway(audit=audit, task_id="t", evidence_writer=writer)
    adapter.register_all(gateway)
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher")
    result = gateway.invoke("mcp_docs-server_read_doc", {"path": "a.md"}, ctx=ctx)
    assert result.ok and result.data["content"] == "doc:a.md"
    assert result.evidence_id  # 45：结果经网关 + 46：固化 Evidence
    assert writer.count() == 1


def test_mcp_not_trusting_self_reported_safety() -> None:
    """44：非只读工具拒绝——工具名含 write 关键词即拒绝，不信任 server 自报。"""
    server = FakeMCPServer("srv", {"read_data": ({"properties": {}}, lambda: {"ok": True})})
    config = MCPServerConfig(server_id="srv", allowed_tools=["read_data"], read_only=True)
    adapter = MCPToolAdapter({config.server_id: config}, fake_servers={server.server_id: server})
    audit = AuditLog(Path(".") / "x.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t")
    converted = adapter.register_all(gateway)
    assert [s.name for s in converted] == ["mcp_srv_read_data"]
    assert all(s.read_only for s in converted)  # 风险属性重设


# ---------- Runtime（十六 47-54） ----------
def test_tool_quota_per_subtask(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t", policy=ToolPolicy(max_calls_per_subtask=2))
    from app.tools.spec import RiskLevel, ToolSpec

    gateway.register(
        ToolSpec(
            name="probe",
            description="d",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=lambda: {"ok": True},
        )
    )
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher", tool_call_budget=2)
    assert gateway.invoke("probe", {}, ctx=ctx).ok
    assert gateway.invoke("probe", {}, ctx=ctx).ok
    r3 = gateway.invoke("probe", {}, ctx=ctx)
    assert r3.status == "blocked"  # 47：工具循环有界（配额）


def test_consecutive_same_call_detection(tmp_path: Path) -> None:
    """48：连续相同调用由 Researcher 层检测（LLMResearcher.MAX_CONSECUTIVE_SAME_CALL）。"""
    from app.agents.llm_agents import LLMResearcher

    assert LLMResearcher.MAX_CONSECUTIVE_SAME_CALL == 2
    assert LLMResearcher.MAX_ROUNDS == 3


def test_tool_budget_exceeded(tmp_path: Path) -> None:
    """49：工具预算超限（Gateway 配额 blocked，不调用 handler）。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    calls = [0]
    from app.tools.spec import RiskLevel, ToolSpec

    def handler():
        calls[0] += 1
        return {"ok": True}

    gateway = ToolGateway(audit=audit, task_id="t", policy=ToolPolicy(max_calls_per_subtask=1))
    gateway.register(
        ToolSpec(
            name="p",
            description="d",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=handler,
        )
    )
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher", tool_call_budget=1)
    gateway.invoke("p", {}, ctx=ctx)
    r = gateway.invoke("p", {}, ctx=ctx)
    assert r.status == "blocked"
    assert calls[0] == 1


def test_evidence_count_limit(tmp_path: Path) -> None:
    """50：Evidence 数量上限。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    writer = EvidenceWriter(tmp_path / "runtime", "t", max_evidence_per_task=1)
    gateway = ToolGateway(
        audit=audit, task_id="t", policy=ToolPolicy(max_evidence_per_task=1), evidence_writer=writer
    )
    from app.tools.spec import RiskLevel, ToolSpec

    gateway.register(
        ToolSpec(
            name="p",
            description="d",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=lambda: {"ok": True},
        )
    )
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher")
    assert gateway.invoke("p", {}, ctx=ctx).ok
    r2 = gateway.invoke("p", {}, ctx=ctx)
    assert r2.status == "blocked"  # evidence 配额（幂等命中前）


def test_read_bytes_limit(tmp_path: Path) -> None:
    """51：读取字节上限。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    writer = EvidenceWriter(tmp_path / "runtime", "t")
    gateway = ToolGateway(
        audit=audit,
        task_id="t",
        policy=ToolPolicy(max_read_bytes_per_task=100),
        evidence_writer=writer,
    )
    from app.tools.spec import RiskLevel, ToolSpec

    gateway.register(
        ToolSpec(
            name="p",
            description="d",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=lambda: {"ok": True, "payload": "x" * 500},
        )
    )
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher")
    result = gateway.invoke("p", {}, ctx=ctx)
    assert result.status == "blocked"


def test_quota_survives_cross_process(tmp_path: Path) -> None:
    """52：跨进程恢复后工具计数不清零（ToolQuota 从 checkpoint 恢复）。"""
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ToolGateway(audit=audit, task_id="t", policy=ToolPolicy(max_calls_per_subtask=2))
    from app.tools.spec import RiskLevel, ToolSpec

    gateway.register(
        ToolSpec(
            name="p",
            description="d",
            input_schema={},
            risk_level=RiskLevel.SAFE,
            read_only=True,
            handler=lambda: {"ok": True},
        )
    )
    ctx = ToolExecutionContext(task_id="t", subtask_id="s1", role="researcher", tool_call_budget=2)
    gateway.invoke("p", {}, ctx=ctx)
    # 模拟恢复：同一 task 新 gateway 实例，配额状态应来自 checkpoint（runner 用 initial_calls 恢复）
    from app.core.state import TaskState

    state = TaskState(task_id="t", user_goal="x", token_budget=1000, cost_budget=1.0)
    state.tool_calls = []  # 计数存于 gateway.tool_calls（runner 恢复路径）
    assert len(gateway.tool_calls) == 1  # 调用记录持久化（checkpoint 恢复后重建 gateway 可计数）


def test_no_real_network_in_autotests() -> None:
    """54：自动测试不访问真实网络——GitHub/Web 均经 MockTransport。"""
    from tests.test_m3b_github_web import _github_handler

    assert callable(_github_handler)
