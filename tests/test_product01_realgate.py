"""PRODUCT-01 REAL GATE 修复验证（020-B）。

真实重放暴露的真实缺陷：
1. LLM 提议工具参数含 Schema 外幻觉字段 → handler(**args) unexpected keyword
   argument 崩溃 → GitHub 数据 0 claims。
2. "GitHub 热门项目" 需要按 stars 排序，工具原先不支持。

修复：ToolGateway 调用前按 input_schema 白名单过滤参数；github_search_repositories
支持 sort/order。本测试全部 MockTransport，零真实网络。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.gateway.tool_policy import ToolExecutionContext
from app.tools.github_client import GitHubClient
from app.tools.github_tools import build_github_tools


def _github_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/search/repositories":
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "items": [
                    {
                        "full_name": "octo/agent",
                        "description": "an agent",
                        "stargazers_count": 100,
                        "language": "Python",
                        "updated_at": "2026-08-01T00:00:00Z",
                    }
                ],
            },
        )
    return httpx.Response(404, json={"message": "not found"})


def test_github_search_supports_stars_sort() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = request.url.params.get("q", "")
        captured["sort"] = request.url.params.get("sort", "")
        captured["order"] = request.url.params.get("order", "")
        return _github_handler(request)

    client = GitHubClient(token="t", transport=httpx.MockTransport(handler))
    tools = {s.name: s for s in build_github_tools(client)}
    spec = tools["github_search_repositories"]
    result = spec.handler(query="agent", per_page=5, sort="stars", order="desc")
    assert result["ok"] is True
    assert captured["query"] == "agent"
    assert captured["sort"] == "stars"
    assert captured["order"] == "desc"


def test_tool_gateway_filters_extra_args(tmp_path: Path) -> None:
    """LLM 幻觉参数（schema 外）不再导致 handler 崩溃；仅 schema 内参数被传递。"""
    client = GitHubClient(token="t", transport=httpx.MockTransport(_github_handler))
    tools = {s.name: s for s in build_github_tools(client)}
    gateway = ToolGateway(audit=AuditLog(tmp_path / "audit.jsonl"), task_id="t-real")
    gateway.register(tools["github_search_repositories"])
    ctx = ToolExecutionContext(
        task_id="st1",
        subtask_id="st1",
        role="researcher",
        tool_call_budget=3,
        replay=False,
    )
    # 幻觉参数：q（错误字段名）、page（schema 外）——修复前 handler(**args) 崩溃
    result = gateway.invoke(
        "github_search_repositories",
        {"q": "agent", "query": "agent", "per_page": 5, "page": 2, "sort": "stars"},
        ctx=ctx,
    )
    assert result.ok is True
    assert result.data.get("ok") is True
    assert result.data.get("repositories") == [
        {
            "full_name": "octo/agent",
            "description": "an agent",
            "stars": 100,
            "language": "Python",
            "updated_at": "2026-08-01T00:00:00Z",
        }
    ]
    # 幻觉字段被过滤（handler 收到合法参数）；audit 日志记录丢弃行为
    audit_text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "tool_args_dropped" in audit_text


def test_github_search_spec_includes_sort() -> None:
    client = GitHubClient(token="t", transport=httpx.MockTransport(_github_handler))
    spec = next(s for s in build_github_tools(client) if s.name == "github_search_repositories")
    assert "sort" in spec.input_schema
    assert "order" in spec.input_schema


@pytest.mark.parametrize(
    ("index", "args", "expected_status"),
    [
        (1, {"query": "agent", "per_page": 1}, "ok"),
        (2, {"query": "multi agent", "per_page": 5}, "ok"),
        (3, {"query": "agent", "per_page": 0}, "ok"),
        (4, {"query": "agent", "per_page": 101}, "ok"),
        (5, {"query": "agent", "per_page": 5, "sort": "stars"}, "ok"),
        (6, {"query": "agent", "per_page": 5, "sort": "updated"}, "ok"),
        (7, {"query": "agent", "per_page": 5, "sort": "forks"}, "ok"),
        (8, {"query": "agent", "per_page": 5, "sort": "stars", "order": "asc"}, "ok"),
        (9, {"query": "agent", "per_page": 5, "sort": "stars", "order": "desc"}, "ok"),
        (10, {"query": " agent ", "per_page": 5}, "ok"),
        (11, {"query": "agent", "per_page": 5, "unknown": "drop-me"}, "ok"),
        (12, {"query": "agent", "per_page": 5, "page": 2}, "ok"),
        (13, {"query": "agent", "per_page": 5, "q": "ignored"}, "ok"),
        (14, {"query": "none", "per_page": 5}, "empty"),
        (15, {"query": "rate", "per_page": 5}, "rate_limited"),
        (16, {"query": "malformed", "per_page": 5}, "network"),
        (17, {"per_page": 5}, "argument_error"),
        (18, {"query": "", "per_page": 5}, "invalid"),
        (19, {"query": "x" * 201, "per_page": 5}, "invalid"),
        (20, {"query": "agent", "per_page": 5, "sort": "invalid", "order": "sideways"}, "ok"),
    ],
)
def test_github_tool_twenty_argument_variants(
    tmp_path: Path, index: int, args: dict, expected_status: str
) -> None:
    """PRODUCT-02 calibration: 20 bounded variants through the real Gateway contract."""

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("q", "")
        if query == "rate":
            return httpx.Response(429, json={"message": "rate limited"})
        if query == "malformed":
            return httpx.Response(200, content=b"not-json")
        if query == "none":
            return httpx.Response(200, json={"total_count": 0, "items": []})
        return _github_handler(request)

    client = GitHubClient(token="t", transport=httpx.MockTransport(handler))
    spec = next(s for s in build_github_tools(client) if s.name == "github_search_repositories")
    gateway = ToolGateway(AuditLog(tmp_path / f"audit-{index}.jsonl"), f"variant-{index}")
    gateway.register(spec)
    result = gateway.invoke(
        "github_search_repositories",
        args,
        ctx=ToolExecutionContext(
            task_id=f"v{index}", subtask_id=f"v{index}", role="researcher",
            tool_call_budget=1, replay=False,
        ),
    )
    if expected_status == "argument_error":
        assert not result.ok and result.status == "argument_error"
    elif expected_status == "empty":
        assert result.ok and result.data["repositories"] == []
    elif expected_status in {"rate_limited", "network", "invalid"}:
        assert result.ok and result.data["ok"] is False
        assert result.data["code"] == expected_status
    else:
        assert result.ok and result.data["ok"] is True
