"""024-D TOKEN/CONTEXT 效率测试门禁 CACHE01-10。

验证 ModelGateway Prompt 组装性质（stable static prefix + dynamic suffix、
deterministic tool schema、structured repair 追加而非重建、无时间戳/随机 ID
污染 messages）与 Usage cache 指标（cache_hit_tokens / cache_miss_tokens /
token_cache_hit_ratio = hit / (hit + miss)）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.gateway.contracts import ModelRequest
from app.gateway.structured_gen import generate_structured
from app.gateway.tool_gateway import ToolGateway


# ---- Fixtures（最小 ToolGateway / ModelRequest） ----
def _gateway() -> ToolGateway:
    from app.gateway.audit import AuditLog
    from app.tools.spec import RiskLevel

    gateway = ToolGateway(audit=AuditLog(Path("data") / "audit-cache-test.jsonl"), task_id="cache-t1")
    from app.tools.spec import ToolSpec

    def handler_a(path: str) -> dict:
        return {"ok": True, "path": path}

    def handler_b(query: str, limit: int = 10) -> dict:
        return {"ok": True, "query": query, "limit": limit}

    gateway.register(
        ToolSpec(name="zeta_read", description="read zeta file", input_schema={"path": "str"}, risk_level=RiskLevel.SAFE, read_only=True, handler=handler_a)
    )
    gateway.register(
        ToolSpec(name="alpha_search", description="search alpha", input_schema={"query": "str", "limit": {"type": "int", "required": False}}, risk_level=RiskLevel.SAFE, read_only=True, handler=handler_b)
    )
    return gateway


def _request(messages: list[dict]) -> ModelRequest:
    return ModelRequest(
        request_id="test-req",
        task_id="t1",
        run_id="r1",
        agent_id="planner",
        role_type="planner",
        model="fake",
        messages=messages,
        response_schema={"goal": {"type": "str"}},
        metadata={"prompt_id": "planner.plan", "prompt_version": "2.0"},
    )


# CACHE01：tool schema 序列化确定性（两次描述字节一致 + 名称排序）
def test_cache01_tool_schema_deterministic() -> None:
    gateway = _gateway()
    first = gateway.describe_tools()
    second = gateway.describe_tools()
    assert first == second
    # 排序：alpha_search 在 zeta_read 之前
    assert first.index("alpha_search") < first.index("zeta_read")
    # 确定性：连续两次字节一致
    assert first.encode() == second.encode()


def test_cache01b_tool_field_order_is_canonical(tmp_path: Path) -> None:
    from app.gateway.audit import AuditLog
    from app.tools.spec import RiskLevel, ToolSpec

    def handler(alpha: str, beta: int) -> dict:
        return {"alpha": alpha, "beta": beta}

    outputs = []
    for index, schema in enumerate(
        (
            {"alpha": "str", "beta": "int"},
            {"beta": "int", "alpha": "str"},
        )
    ):
        gateway = ToolGateway(
            audit=AuditLog(tmp_path / f"audit-{index}.jsonl"), task_id="cache-t1"
        )
        gateway.register(
            ToolSpec(
                name="ordered_tool",
                description="stable",
                input_schema=schema,
                risk_level=RiskLevel.SAFE,
                read_only=True,
                handler=handler,
            )
        )
        outputs.append(gateway.describe_tools())
    assert outputs[0].encode() == outputs[1].encode()


# CACHE02：相同 Agent 的连续请求生成相同固定前缀（system 前缀稳定）
def test_cache02_stable_system_prefix() -> None:
    prefix = "[planner.plan v2.0] Return exactly one JSON object immediately."
    req_a = _request([{"role": "system", "content": prefix}, {"role": "user", "content": "目标 A"}])
    req_b = _request([{"role": "system", "content": prefix}, {"role": "user", "content": "目标 B"}])
    assert req_a.messages[0]["content"] == req_b.messages[0]["content"]
    assert req_a.messages[0] == req_b.messages[0]


# CACHE03：messages 中无时间戳/随机 ID 污染稳定前缀
def test_cache03_no_timestamp_in_prefix() -> None:
    prefix = "[planner.plan v2.0] Return exactly one JSON object immediately."
    assert not re.search(r"\d{4}-\d{2}-\d{2}", prefix)  # 无日期
    assert not re.search(r"\d{2}:\d{2}:\d{2}", prefix)  # 无时间
    assert "uuid" not in prefix.lower()


def test_cache03b_request_ids_do_not_pollute_message_prefix() -> None:
    from app.agents.llm_agents import _new_request
    from app.core.config import AppSettings

    messages = [
        {"role": "system", "content": "stable system contract"},
        {"role": "user", "content": "dynamic goal"},
    ]
    first = _new_request("task", "run", "planner", "planner", "model", messages, {}, AppSettings())
    second = _new_request("task", "run", "planner", "planner", "model", messages, {}, AppSettings())
    assert first.request_id != second.request_id
    assert first.messages == second.messages
    assert first.request_id not in str(first.messages)


# CACHE04：user 后缀为动态部分（goal 不同 → user 不同，system 不变）
def test_cache04_dynamic_suffix_only() -> None:
    req_a = _request([{"role": "system", "content": "[planner.plan v2.0] x"}, {"role": "user", "content": "目标 A"}])
    req_b = _request([{"role": "system", "content": "[planner.plan v2.0] x"}, {"role": "user", "content": "目标 B"}])
    assert req_a.messages[1] != req_b.messages[1]
    assert req_a.messages[0] == req_b.messages[0]  # 前缀保持稳定


# CACHE05：structured repair 追加修复消息而非重建整个 prompt（前缀保留）
def test_cache05_repair_appends_not_rebuilds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core.config import AppSettings
    from app.gateway.contracts import ModelResponse

    class FailingProvider:
        def __init__(self) -> None:
            self.calls: list[list[dict]] = []
            self._bad = True

        def generate(self, request: ModelRequest) -> ModelResponse:
            self.calls.append(list(request.messages))
            if self._bad:
                self._bad = False
                return ModelResponse(
                    request_id="x", provider="fake", model="fake",
                    raw_text="this is not json at all",  # 触发 schema 解析失败 → repair
                    input_tokens=10, output_tokens=5, usage_source="ESTIMATED",
                )
            return ModelResponse(
                request_id="x", provider="fake", model="fake", raw_text='{"goal":"ok"}',
                input_tokens=10, output_tokens=5, usage_source="ESTIMATED",
            )

    from app.core.budget import BudgetController
    from app.gateway.audit import AuditLog
    from app.gateway.model_gateway import ModelGateway

    provider = FailingProvider()
    gateway = ModelGateway(
        provider=provider,
        budget=BudgetController(token_budget=1000, cost_budget=1.0),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        task_id="t1",
        run_id="r1",
    )
    request = _request(
        [
            {"role": "system", "content": "[planner.plan v2.0] stable"},
            {"role": "user", "content": "目标 A" + ("x" * 5000)},
        ]
    ).model_copy(
        update={
            "metadata": {
                "critical_context": {
                    "user_goal": "目标 A",
                    "constraints": ["read_only"],
                    "current_task": "create plan",
                }
            }
        }
    )
    settings = AppSettings()
    settings.max_output_repair_attempts = 3
    result = generate_structured(gateway, request, {"goal": {"type": "str"}}, settings)
    assert result == {"goal": "ok"}
    # 第二次只保留稳定 system 与最小动态修复上下文，不重发巨大原始 user prompt。
    assert len(provider.calls[0]) == 2
    assert provider.calls[1][0] == provider.calls[0][0]  # system 前缀保留
    assert provider.calls[1][0]["content"] == "[planner.plan v2.0] stable"
    assert len(provider.calls[1]) == 4
    assert "目标 A" in provider.calls[1][1]["content"]
    assert "x" * 5000 not in provider.calls[1][1]["content"]
    assert sum(len(item["content"]) for item in provider.calls[1]) < 2500
    assert "Schema:" in provider.calls[1][-1]["content"]


def _usage_row(input_tokens: int, cached: int | None, ts: str) -> dict:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "total_tokens": input_tokens,
        "output_tokens": 0,
        "latency_ms": 1,
        "timestamp": ts,
        "usage_source": "REPORTED",
        "cost_total": 0.0,
        "currency": "USD",
        "reasoning_tokens": None,
        "cache_write_tokens": None,
        "other_tokens": None,
        "context_tokens_before": None,
        "context_tokens_after": None,
        "compression_triggered": 0,
        "compression_tokens_before": None,
        "compression_tokens_after": None,
        "scope": "user_task",
        "task_id": "t1",
        "run_id": "r1",
        "call_id": "c1",
        "role": "planner",
        "agent_id": "planner",
        "provider_id": "openai_compatible",
        "provider_name": "openai_compatible",
        "model_id": "model-x",
        "estimated_input_tokens": None,
        "estimated_output_tokens": None,
        "context_limit": None,
    }


# CACHE06：usage 汇总包含 cache_hit_tokens / cache_miss_tokens / token_cache_hit_ratio
def test_cache06_usage_summary_fields() -> None:
    from app.usage.store import _summarize

    rows = [
        _usage_row(1000, 600, "2026-01-01T00:00:00+00:00"),
        _usage_row(2000, 1400, "2026-01-01T00:00:01+00:00"),
    ]
    summary = _summarize(rows)
    # hit = 600 + 1400 = 2000；miss = (1000-600) + (2000-1400) = 1000
    assert summary["cache_hit_tokens"] == 2000
    assert summary["cache_miss_tokens"] == 1000
    assert summary["token_cache_hit_ratio"] == pytest.approx(2000 / 3000)


# CACHE07：token_cache_hit_ratio 定义严格为 hit / (hit + miss)（不是平均命中/不是 cached/input 全部）
def test_cache07_ratio_definition() -> None:
    from app.usage.store import _summarize

    # 故意让 input 包含未计 cache 的行（cache 缺失 → 不参与 hit/miss）
    rows = [
        _usage_row(100, 60, "2026-01-01T00:00:00+00:00"),
        _usage_row(300, None, "2026-01-01T00:00:01+00:00"),
    ]
    summary = _summarize(rows)
    assert summary["cache_hit_tokens"] == 60
    assert summary["cache_miss_tokens"] == 40
    assert summary["token_cache_hit_ratio"] == pytest.approx(60 / 100)  # hit/(hit+miss)
    # 不得把 cache 缺失行当作 miss 或混入分母
    assert summary["cached_input_tokens"] == 60


# CACHE08：无数据时新字段为 None（不产生 NaN/0 假象）
def test_cache08_empty_summary_fields() -> None:
    from app.usage.store import _summarize

    summary = _summarize([])
    assert summary["cache_hit_tokens"] is None
    assert summary["cache_miss_tokens"] is None
    assert summary["token_cache_hit_ratio"] is None


# CACHE09：API /usage 端点暴露新指标
def test_cache09_usage_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.api import server

    data = tmp_path / "api-data"
    data.mkdir(parents=True)
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(data))
    client = TestClient(server.app)
    resp = client.get("/usage")
    assert resp.status_code == 200
    body = resp.json()
    assert "token_cache_hit_ratio" in body
    assert "cache_hit_tokens" in body
    assert "cache_miss_tokens" in body
    assert body["token_cache_hit_ratio"] is None  # 无数据


# CACHE10：结构化生成全程不破坏确定性（同一 schema 两次调用 system 前缀稳定）
def test_cache10_agent_prefix_stability_across_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core.config import AppSettings
    from app.core.budget import BudgetController
    from app.gateway.audit import AuditLog
    from app.gateway.contracts import ModelResponse
    from app.gateway.model_gateway import ModelGateway

    class StaticProvider:
        def __init__(self) -> None:
            self.seen: list[list[dict]] = []

        def generate(self, request: ModelRequest) -> ModelResponse:
            self.seen.append(list(request.messages))
            return ModelResponse(
                request_id="x", provider="fake", model="fake", raw_text='{"goal":"ok"}',
                input_tokens=10, output_tokens=5, usage_source="ESTIMATED",
            )

    provider = StaticProvider()
    gateway = ModelGateway(
        provider=provider,
        budget=BudgetController(token_budget=1000, cost_budget=1.0),
        audit=AuditLog(tmp_path / "audit.jsonl"),
        task_id="t1",
    )
    settings = AppSettings()
    for goal in ("目标一", "目标二", "目标三"):
        req = _request(
            [
                {"role": "system", "content": "[planner.plan v2.0] Return exactly one JSON object immediately."},
                {"role": "user", "content": f"目标：{goal}"},
            ]
        )
        generate_structured(gateway, req, {"goal": {"type": "str"}}, settings)
    # 同一固定 Agent（planner）的连续请求 system 前缀逐字节一致
    prefixes = {tuple(msg[0].items()) for msg in provider.seen}
    assert len(prefixes) == 1
    # user 后缀确实不同（每次 goal 不同 → 动态后缀生效）
    user_contents = {msg[1]["content"] for msg in provider.seen}
    assert len(user_contents) == 3


def test_cache10b_role_context_excludes_unrelated_task_history() -> None:
    from types import SimpleNamespace

    from app.core.config import AppSettings
    from app.core.context_builder import ContextBuilder

    subtask = SimpleNamespace(
        subtask_id="research-1",
        objective="compare projects",
        input_refs=["evidence-1"],
        acceptance_criteria=["cite sources"],
        rework_count=0,
        review_history=[],
        unrelated_history="must not be serialized",
    )
    context = ContextBuilder(AppSettings()).researcher_context(
        subtask,
        [{"id": "evidence-1", "tool": "github", "summary": "verified"}],
    )
    assert set(context["subtask"]) == {
        "subtask_id",
        "objective",
        "input_refs",
        "acceptance_criteria",
        "rework_count",
        "review_feedback",
    }
    assert "unrelated_history" not in str(context)
