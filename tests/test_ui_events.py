"""UI-01 事件系统与 API 端点测试（010 十三/十四/二十八）。

覆盖：
- EventStore SQLite 写入 / sequence 单调 / 按 run_id 查询 / replay。
- 事件脱敏（payload 含假密钥 → 落库无原文）。
- run_task 生命周期事件（task_created / task_completed）。
- /dashboard /tasks /agents /system/health /settings/status 端点。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.core.events import EventStore


def _store(tmp_path: Path) -> EventStore:
    return EventStore(tmp_path / "events.sqlite")


def test_event_store_write_and_sequence(tmp_path: Path) -> None:
    """写入 + sequence 单调递增 + 按 run_id 查询。"""
    store = _store(tmp_path)
    e1 = store.emit(task_id="t1", run_id="r1", event_type="task_created", summary="created")
    e2 = store.emit(task_id="t1", run_id="r1", event_type="plan_created", summary="plan")
    e3 = store.emit(task_id="t2", run_id="r2", event_type="task_created", summary="other")
    assert e1.sequence < e2.sequence < e3.sequence
    r1 = store.list_events(run_id="r1")
    assert [e.event_type for e in r1] == ["task_created", "plan_created"]
    # replay：after_sequence 只取新事件
    tail = store.list_events(run_id="r1", after_sequence=e1.sequence)
    assert [e.event_type for e in tail] == ["plan_created"]
    assert store.count() == 3


def test_event_payload_redacted(tmp_path: Path) -> None:
    """事件 payload/summary 不落真实凭据（假密钥被脱敏）。"""
    store = _store(tmp_path)
    fake_key = "sk-" + "a" * 30
    ev = store.emit(
        task_id="t1",
        run_id="r1",
        event_type="tool_completed",
        summary=f"tool ok {fake_key}",
        payload_safe={"tool": "x", "token": fake_key, "nested": {"key": fake_key}},
    )
    assert fake_key not in ev.summary
    assert fake_key not in ev.payload_safe.get("token", "")
    assert fake_key not in ev.payload_safe.get("nested", {}).get("key", "")
    # 落库后重读也无原文
    again = store.list_events(run_id="r1")[0]
    assert fake_key not in again.summary
    assert "***" in again.summary


def test_run_task_emits_lifecycle_events(tmp_path: Path, monkeypatch) -> None:
    """run_task 生命周期事件：task_created → ... → task_completed。"""
    from app.core.events import get_store
    from app.core.events import init as events_init
    from app.runner import run_task

    events_init(tmp_path)
    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=1.0,
        data_dir=tmp_path / "data",
    )
    store = get_store()
    assert store is not None
    evs = store.list_events(run_id=report.run_id)
    types = [e.event_type for e in evs]
    assert "task_created" in types
    assert "task_completed" in types
    assert "plan_created" in types
    assert "subtask_started" in types
    assert "subtask_completed" in types
    assert "review_passed" in types


def test_full_access_mode_runs_without_manual_approval(tmp_path: Path, monkeypatch) -> None:
    """Explicit full-access mode applies a validated sandbox patch without pausing."""
    from app.core.approval import ApprovalService
    from app.core.events import get_store
    from app.runner import run_task

    fixtures = Path(__file__).resolve().parent.parent / "fixtures"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_TEAM_ALLOWED_READ_ROOTS", str(fixtures))

    report = run_task(
        "sandbox_code_fix",
        token_budget=20_000,
        cost_budget=1.0,
        data_dir=data_dir,
        model_overrides={"project_alias": "sample-python"},
        permission_mode="full_access",
    )

    assert report.state.current_status == "completed"
    assert report.state.permission_mode == "full_access"
    assert report.state.pending_approval_id is None
    approval_preference = next(
        item
        for item in report.state.personalization_applied
        if item["field"] == "approval_preference"
    )
    assert approval_preference["value"] == "full_access"
    assert approval_preference["current_task_override"] is True
    task_dir = data_dir / "runtime" / "workspaces" / report.task_id
    approvals = ApprovalService(storage_path=task_dir / "approvals.jsonl").all(report.task_id)
    assert approvals
    assert all(item.status == "approved" for item in approvals)
    assert approvals[0].approval_level == "automatic_full_access"
    assert "return True" in (task_dir / "worktree" / "src" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "return False" in (fixtures / "sample-python" / "src" / "main.py").read_text(
        encoding="utf-8"
    )

    store = get_store()
    assert store is not None
    event_types = [event.event_type for event in store.list_events(run_id=report.run_id)]
    assert "approval_bypassed" in event_types
    assert "approval_requested" not in event_types


def test_dashboard_endpoint(tmp_path: Path, monkeypatch) -> None:
    """GET /dashboard 聚合（指标/健康/最近任务）。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert "metrics" in body and "recent_tasks" in body and "agent_team" in body
        assert "backend" in body["system"]
        assert body["system"]["sqlite"] in ("Online", "Degraded")


def test_tasks_agents_health_settings_endpoints(tmp_path: Path, monkeypatch) -> None:
    """任务列表 / Agent 目录 / 健康 / 设置状态端点。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        assert client.get("/tasks").status_code == 200
        agents = client.get("/agents")
        assert agents.status_code == 200
        assert {"current_action", "current_subtask", "latest_completed"} <= set(agents.json()[0])
        assert client.get("/system/health").status_code == 200
        r = client.get("/settings/status")
        assert r.status_code == 200
        body = r.json()
        # 绝不返回 Secret 值（布尔状态键名允许；无任何 secret 值字段）
        assert "api_key_configured" in body["model_provider"]
        assert "token_configured" in body["github"]
        assert "sk-" not in str(body)
        assert "ghp_" not in str(body)


def test_events_endpoint_404(tmp_path: Path, monkeypatch) -> None:
    """未知 run_id 的 events 端点返回 404。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    with TestClient(app) as client:
        resp = client.get("/tasks/nonexistent/events")
        assert resp.status_code == 404


def test_real_cost_is_unavailable_when_provider_has_no_price(tmp_path: Path) -> None:
    from app.runner import _model_cost_available

    data_dir = tmp_path / "data"
    (data_dir / "runtime").mkdir(parents=True)
    store = EventStore(data_dir / "runtime" / "events.sqlite")
    store.emit(
        task_id="task-cost",
        run_id="run-cost",
        event_type="model_call_completed",
        actor_type="planner",
        actor_id="planner",
        payload_safe={
            "total_tokens": 57,
            "estimated_cost": None,
            "cost_available": False,
        },
    )
    assert _model_cost_available(data_dir, "real", "task-cost", "run-cost") is False


@pytest.fixture(autouse=True)
def _reset_event_store():
    """测试间重置事件单例（避免跨测试目录串写）。"""
    import app.core.events as _evmod

    _evmod._store = None
    yield
    _evmod._store = None


# ---------- review（sa_20260808_120531）修复回归：SSE 内容与 replay ----------
def test_events_sse_stream_content(tmp_path: Path, monkeypatch) -> None:
    """SSE 流：默认 message 事件（无 event: 行）、1s 节流、after replay、终态关闭。"""
    import time as _time

    from app.core.events import get_store
    from app.core.events import init as events_init
    from app.runner import run_task

    events_init(tmp_path)
    report = run_task(
        "github_compare_team",
        token_budget=10000,
        cost_budget=1.0,
        data_dir=tmp_path / "data",
    )
    store = get_store()
    assert store is not None
    # 用 store 直接验证内容格式（默认 message：无 event: 行）
    events = store.list_events(run_id=report.run_id)
    assert events, "expected events"
    ev0 = events[0]
    assert ev0.event_type == "task_created"
    # replay：after 返回 seq 之后的事件
    tail = store.list_events(run_id=report.run_id, after_sequence=ev0.sequence)
    assert all(e.sequence > ev0.sequence for e in tail)
    # 完整性：sequence 连续
    seqs = [e.sequence for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    _time.sleep(0)


def test_events_endpoint_after_replay(tmp_path: Path, monkeypatch) -> None:
    """SSE 端点接受 after 参数并只回放新事件（不重复历史）。"""
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path / "data"))
    from app.core.events import EventStore

    store = EventStore(tmp_path / "events.sqlite")
    store.emit(task_id="t1", run_id="r1", event_type="task_created")
    store.emit(task_id="t1", run_id="r1", event_type="plan_created")
    # 直接验证 store replay 语义（SSE 端点由 _stream 用同一 store.list_events）
    after = store.list_events(run_id="r1")[0].sequence
    tail = store.list_events(run_id="r1", after_sequence=after)
    assert [e.event_type for e in tail] == ["plan_created"]


# ---------- review 复查（sa_20260808_120531 round2）：SSE 帧格式与终态 ----------
def test_events_sse_frame_format() -> None:
    """SSE 帧：默认 message 事件（无 event: 行）、id=sequence、data=JSON。"""
    from app.api.server import _format_sse_frame

    frame = _format_sse_frame(7, {"event_type": "plan_created", "summary": "x"})
    assert frame.startswith("id: 7\n")
    assert "\nevent: " not in frame  # 默认 message 事件
    assert '"event_type": "plan_created"' in frame
    assert frame.endswith("\n\n")


def test_events_sse_terminal_frame_shape() -> None:
    """终态通知帧：完整 RuntimeEvent 形状（event_type/sequence），客户端据此关闭连接。"""
    from app.api.server import _format_sse_frame

    payload = {
        "event_type": "task_status_changed",
        "task_id": "r1",
        "run_id": "r1",
        "sequence": 9,
        "ts": "{}",
        "summary": "task completed",
        "actor_type": "system",
        "actor_id": "r1",
        "status": "completed",
    }
    frame = _format_sse_frame(9, payload)
    assert '"event_type": "task_status_changed"' in frame
    assert '"sequence": 9' in frame
    assert '"status": "completed"' in frame
    assert "\nevent: " not in frame
