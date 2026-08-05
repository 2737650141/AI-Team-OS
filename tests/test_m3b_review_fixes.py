"""006 审查修复回归（review sa_20260805_035741）：Blocking/should-fix 验证。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.core.budget import BudgetController
from app.core.config import AppSettings, ModelProviderSettings
from app.core.context_builder import ContextBuilder
from app.core.evidence import EvidenceWriter
from app.core.ssrf import blocked_ip_reason
from app.core.state import SubtaskState, TaskState
from app.gateway.audit import AuditLog
from app.gateway.fake_provider import FakeModelProvider
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolPolicy
from app.runner import _build_context
from app.tools.github_client import GitHubClient
from app.tools.github_tools import build_github_tools
from app.tools.local_file import LocalPathPolicy, build_local_tools


def _settings() -> AppSettings:
    return AppSettings(model=ModelProviderSettings(default_model="test-model", enable_real=True))


def _real_researcher_env(tmp_path: Path):
    """构造 real 模式 Researcher 环境（github 工具 + 顺序响应 Provider）。"""
    responses: list[str] = []

    class SeqProvider(FakeModelProvider):
        def generate(self, req):
            self.call_count += 1
            idx = self.call_count - 1
            if idx < len(responses):
                text = responses[idx]
            else:
                text = '{"round": 1, "done": true, "tool_calls": []}'
            from app.gateway.contracts import ModelResponse

            return ModelResponse(
                request_id=req.request_id,
                provider="fake",
                model=req.model,
                raw_text=text,
                input_tokens=10,
                output_tokens=10,
                estimated_cost=0.0,
            )

    provider = SeqProvider()
    audit = AuditLog(tmp_path / "audit.jsonl")
    budget = BudgetController(1_000_000, 10.0)
    gw = ModelGateway(provider=provider, budget=budget, audit=audit, task_id="t")
    tgw = ToolGateway(
        audit=audit,
        task_id="t",
        policy=ToolPolicy(),
        evidence_writer=EvidenceWriter(tmp_path / "runtime", "t"),
    )
    for spec in build_github_tools(
        GitHubClient(
            token="",
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"full_name": "x/y", "stars": 1})
            ),
        )
    ):
        tgw.register(spec)

    router = ModelRouter(AppSettings().routing)
    return gw, tgw, router, provider, responses


def test_researcher_tool_loop_role_whitelist_ok(tmp_path: Path) -> None:
    """Blocking-1：LLMResearcher 工具循环 ctx.role=researcher 与工具白名单匹配，
    工具调用成功并固化 Evidence（此前 role=researcher:s1 被精确匹配拒绝）。"""
    from app.agents.llm_agents import LLMResearcher

    gw, tgw, router, provider, responses = _real_researcher_env(tmp_path)
    responses.append(
        '{"round": 1, "done": false, "tool_calls": [{"tool": "github_repo_info", '
        '"args": {"repo": "x/y"}}]}'
    )
    responses.append('{"round": 2, "done": true, "tool_calls": []}')
    responses.append(
        '{"summary": "ok", "claims": [{"claim_id": "c1", "text": "repo exists", '
        '"evidence_ids": [], "confidence": 0.8}], "evidence_refs": [], '
        '"unverified_items": [], "confidence": 0.8}'
    )
    researcher = LLMResearcher(gw, router, ContextBuilder(_settings()), _settings(), tgw)
    subtask = SubtaskState(
        subtask_id="s1",
        title="t",
        objective="o",
        dependencies=[],
        assigned_role="researcher",
        input_refs=[],
        expected_output="r",
        acceptance_criteria=["a"],
        token_budget=1000,
        tool_call_budget=3,
    )
    result = researcher.run(subtask, [subtask])
    assert result.evidence_refs  # github_repo_info 调用成功并固化 Evidence
    assert any(t["status"] == "ok" for t in tgw.tool_calls)
    # 无证据 claim 被标记未验证（十二）
    assert any("无证据" in item for item in result.unverified_items)


def test_project_alias_traversal_rejected(tmp_path: Path) -> None:
    """Blocking-2：project_alias 含 .. 等字符被确定性拒绝。"""
    state = TaskState(task_id="t", user_goal="x", token_budget=1000, cost_budget=1.0)
    with pytest.raises(ValueError, match="project_alias"):
        _build_context(
            state,
            tmp_path / "data",
            model_mode="fake",
            model_overrides={"project_alias": "../../etc"},
        )


def test_evidence_show_traversal_rejected(tmp_path: Path) -> None:
    """should-fix-1：evidence_id 非十六进制（穿越模式）被拒绝。"""
    from app.runner import evidence_show

    with pytest.raises(KeyError, match="invalid evidence_id"):
        evidence_show("../../etc/passwd", data_dir=tmp_path / "data")


def test_ipv4_mapped_rejected() -> None:
    """should-fix-2：IPv4-mapped 云元数据地址被拒绝。"""
    assert blocked_ip_reason("::ffff:169.254.169.254") is not None
    assert blocked_ip_reason("::ffff:127.0.0.1") is not None
    assert blocked_ip_reason("::ffff:8.8.8.8") is None


def test_sensitive_dir_case_insensitive(tmp_path: Path) -> None:
    """should-fix-5：Windows 大小写不敏感——.SSH/.GIT 目录同样拒绝。"""
    root = tmp_path / "proj"
    (root / ".SSH").mkdir(parents=True)
    (root / ".SSH" / "config").write_text("x", encoding="utf-8")
    policy = LocalPathPolicy([root])
    with pytest.raises(Exception) as exc_info:
        policy.validate(".SSH/config")
    assert "sensitive" in str(exc_info.value)


def test_role_used_tool_calls_dual_matching() -> None:
    """review 复查：role_used_tool_calls 双口径（researcher 与 researcher:s1 都统计）。"""
    from app.agents.reviewer import role_used_tool_calls
    from app.core.state import TaskState

    state = TaskState(task_id="t", user_goal="x", token_budget=1000, cost_budget=1.0)
    state.tool_calls = [
        {"role": "researcher", "subtask_id": "s1", "idempotency_key": "k1"},  # 新格式（LLM 循环）
        {"role": "researcher:s1", "idempotency_key": "k2"},  # 旧格式（Fake 口径）
        {"role": "researcher:s2", "idempotency_key": "k3"},  # 旧格式
    ]
    assert role_used_tool_calls(state, "researcher", "s1") == 2  # 精确 + 旧口径都算
    assert role_used_tool_calls(state, "researcher", "s2") == 1


def test_local_list_root_default(tmp_path: Path) -> None:
    """Nit：local_list_directory 默认列出根目录。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    policy = LocalPathPolicy([root])
    tools = {s.name: s for s in build_local_tools(policy)}
    r = tools["local_list_directory"].handler("")
    assert r["ok"] and any(e["name"] == "a.txt" for e in r["entries"])


def test_evidence_dedup_before_quota(tmp_path: Path) -> None:
    """Nit：配额满后重复内容仍可去重返回（不抛配额异常）。"""
    from app.core.evidence import EvidenceWriter

    w = EvidenceWriter(tmp_path / "runtime", "t", max_evidence_per_task=1)
    a = w.write(tool_name="t", source_type="local", source_uri="u1", content="same")
    b = w.write(tool_name="t", source_type="local", source_uri="u2", content="same")
    assert a.evidence_id == b.evidence_id  # 去重优先于配额
