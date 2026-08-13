"""Agent Registry 测试（004 五，测试要求 1-3）。"""

from __future__ import annotations

import pytest

from app.core.registry import AgentRegistry, default_registry
from app.core.schemas import AgentSpec


def test_default_registry_has_five_roles() -> None:
    registry = default_registry()
    assert len(registry.all()) == 5
    role_types = {a.role_type for a in registry.all()}
    assert role_types == {"supervisor", "planner", "researcher", "executor", "reviewer"}


def test_executor_registered_but_disabled() -> None:
    """Executor 已注册且已启用（007 十二：M3-C 正式启用）。"""
    registry = default_registry()
    executor = registry.get("executor")
    assert executor.role_type == "executor"
    assert executor.enabled is True  # 007 十二：M3-C 启用
    assert registry.is_enabled("executor") is True
    assert "executor" in [a.agent_id for a in registry.all()]


def test_unknown_agent_rejected() -> None:
    """未知 Agent 拒绝（测试要求 2）。"""
    registry = default_registry()
    with pytest.raises(KeyError):
        registry.get("ghost_agent")


def test_agent_tool_whitelist() -> None:
    """Agent 工具白名单（测试要求 3）：researcher 仅允许只读工具（fixture + local 只读）。"""
    registry = default_registry()
    researcher = registry.get("researcher")
    # 007 六：researcher 白名单扩展本地只读工具（沙箱任务读取 worktree）
    assert {"fixture_repo_lookup", "fixture_source_lookup"} <= set(researcher.allowed_tools)
    assert {"github_search_repositories", "github_repo_info"} <= set(
        researcher.allowed_tools
    )
    # 全部为只读工具（无沙箱写工具/危险工具）
    assert "sandbox_write_file" not in researcher.allowed_tools
    assert "sandbox_delete_path" not in researcher.allowed_tools


def test_register_disable_dispatch_guard() -> None:
    """注册后禁用：不可被派发（004 五 disabled 约束）。"""
    registry = AgentRegistry()
    registry.register(
        AgentSpec(
            agent_id="temp",
            role_type="researcher",
            display_name="Temp",
            goal="x",
            instructions="x",
            allowed_tools=[],
            enabled=False,
        )
    )
    assert registry.get("temp").enabled is False
    assert registry.by_role("researcher") == []
