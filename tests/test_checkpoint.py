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
    audit = AuditLog(tmp_path / "audit.jsonl")
    gateway = ModelGateway(
        provider=DeterministicFakeModel(),
        budget=BudgetController(token_budget=10000, cost_budget=1.0),
        audit=audit,
        task_id="t1",
    )
    conn = sqlite3.connect(str(tmp_path / "checkpoints.db"), check_same_thread=False)
    saver = SqliteSaver(conn)
    return build_graph(gateway).compile(checkpointer=saver)


def test_sqlite_checkpoint_roundtrip(tmp_path: Path) -> None:
    """任务状态经 SQLite Checkpoint 持久化，可从同一 thread 恢复。"""
    compiled = _make_compiled(tmp_path)
    state = TaskState(task_id="t1", user_goal="hello", token_budget=10000, cost_budget=1.0)

    result = compiled.invoke(state.model_dump(), config={"configurable": {"thread_id": "t1"}})
    final = TaskState.model_validate(result)

    assert final.current_status.value == "completed"
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
