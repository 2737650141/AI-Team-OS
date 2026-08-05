"""SQLite Checkpoint 测试：R14/R18（版本校验）、保存/恢复。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from app.core.budget import BudgetController
from app.core.state import CHECKPOINT_VERSION, TaskState
from app.gateway.audit import AuditLog
from app.gateway.model_gateway import DeterministicFakeModel, ModelGateway
from app.graph import build_graph


def _make_compiled(tmp_path: Path):
    from app.gateway.tool_gateway import ToolGateway
    from app.tools.fixture_repo import DangerousWriteTool, FixtureRepositoryLookupTool
    from tests.conftest import FIXTURE_REPOS

    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ModelGateway(
        provider=DeterministicFakeModel(),
        budget=BudgetController(token_budget=10000, cost_budget=1.0),
        audit=audit,
        task_id="t1",
    )
    tool_gateway = ToolGateway(audit=audit, task_id="t1")
    tool_gateway.register(FixtureRepositoryLookupTool(FIXTURE_REPOS).spec())
    tool_gateway.register(DangerousWriteTool().spec())
    conn = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    return build_graph(gateway, tool_gateway).compile(checkpointer=saver)


def test_sqlite_checkpoint_roundtrip(tmp_path: Path) -> None:
    """任务状态经 SQLite Checkpoint 持久化，可从同一 thread 恢复。"""
    compiled = _make_compiled(tmp_path)
    state = TaskState(task_id="t1", user_goal="hello", token_budget=10000, cost_budget=1.0)

    result = compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": "t1"}})
    final = TaskState.model_validate(result)

    assert final.current_status == "completed"  # 稳定字符串（003-A 四）
    assert isinstance(final.current_status, str)
    assert final.checkpoint_version == CHECKPOINT_VERSION

    # 新实例从 SQLite 恢复同一 thread
    conn2 = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    restored_saver = SqliteSaver(conn2)
    checkpoint = restored_saver.get_tuple(config={"configurable": {"thread_id": "t1"}})
    assert checkpoint is not None
    restored = TaskState.model_validate(checkpoint.checkpoint["channel_values"])
    assert restored.task_id == "t1"
    assert restored.final_result == final.final_result


def test_checkpoint_version_mismatch_rejected(tmp_path: Path) -> None:
    """R18：checkpoint schema 版本不一致时拒绝执行（迁移失败防护）。"""
    compiled = _make_compiled(tmp_path)
    state = TaskState(task_id="t2", user_goal="x", token_budget=10000, cost_budget=1.0)
    state.checkpoint_version = "0.9"  # 模拟旧 schema

    with pytest.raises(RuntimeError, match="checkpoint version mismatch"):
        compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": "t2"}})


def test_unknown_status_rejected() -> None:
    """未知状态值在反序列化时拒绝（003-A 四：Pydantic 边界校验）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TaskState(
            task_id="t3",
            user_goal="x",
            token_budget=1000,
            cost_budget=0.1,
            current_status="bogus",
        )
    with pytest.raises(ValidationError):
        TaskState(
            task_id="t3",
            user_goal="x",
            token_budget=1000,
            cost_budget=0.1,
            failure_code="bogus",
        )
    with pytest.raises(ValidationError):
        TaskState(
            task_id="t3",
            user_goal="x",
            token_budget=1000,
            cost_budget=0.1,
            paused_from_status="bogus",
        )


def test_checkpoint_holds_stable_string(tmp_path: Path) -> None:
    """保存后新进程反序列化：checkpoint 中状态为稳定字符串而非 Enum 实例（003-A 四）。"""
    compiled = _make_compiled(tmp_path)
    state = TaskState(task_id="t4", user_goal="hello", token_budget=10000, cost_budget=1.0)
    compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": "t4"}})

    conn2 = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    restored_saver = SqliteSaver(conn2)
    checkpoint = restored_saver.get_tuple(config={"configurable": {"thread_id": "t4"}})
    assert checkpoint is not None
    raw = checkpoint.checkpoint["channel_values"]["current_status"]
    assert isinstance(raw, str)
    assert raw == "completed"
