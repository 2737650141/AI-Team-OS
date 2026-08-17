from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.server as server
from app.api.server import app
from app.conversation.service import _extract_items
from app.core.task_control import TaskControlStore
from app.runner import list_tasks, resume_task, run_task

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="JARVIS interaction is Windows-only"
)


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    server._settings_cache = None
    return TestClient(app)


def test_ux01_hello_is_conversation_and_not_user_task(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/jarvis/sessions/ux01/turns",
            json={"user_input": "你好", "model_mode": "fake"},
        )
        tasks = client.get("/tasks").json()

    assert response.status_code == 200
    body = response.json()
    assert body["run_kind"] == "conversation"
    assert body["result"]["status"] == "completed"
    assert not body["result"]["summary"].lstrip().startswith("{")
    assert body["session"]["messages"][0] == {"role": "user", "content": "你好"}
    assert body["session"]["messages"][1]["role"] == "assistant"
    assert not body["session"]["messages"][1]["content"].lstrip().startswith("{")
    assert tasks == []


def test_ux02_capability_chat_has_no_approval(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/jarvis/sessions/ux02/turns",
            json={"user_input": "你可以干什么", "model_mode": "fake"},
        )
        run_id = response.json()["result"]["run_id"]
        approvals = client.get(f"/tasks/{run_id}/approvals").json()

    assert response.json()["run_kind"] == "conversation"
    assert approvals == []


def test_latest_user_facing_candidates_outrank_stale_fixture_refs() -> None:
    report = SimpleNamespace(
        state=SimpleNamespace(
            subtasks=[
                SimpleNamespace(
                    superseded=False,
                    input_refs=[
                        "fixture_repo_lookup:langgraph",
                        "fixture_repo_lookup:crewai",
                    ],
                    execution_result=SimpleNamespace(
                        claims=[
                            SimpleNamespace(
                                text=(
                                    "TauricResearch/TradingAgents and "
                                    "FoundationAgents/MetaGPT are candidates."
                                )
                            )
                        ]
                    ),
                )
            ]
        )
    )
    assert _extract_items(report) == [
        "TauricResearch/TradingAgents",
        "FoundationAgents/MetaGPT",
    ]


def test_ux03_work_request_remains_user_task_in_same_session(
    tmp_path: Path, monkeypatch
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/jarvis/sessions/ux03/turns",
            json={"user_input": "比较几个 Agent 项目", "model_mode": "fake"},
        )
        restored = client.get("/jarvis/sessions/ux03").json()
        tasks = client.get("/tasks").json()

    body = response.json()
    assert body["run_kind"] == "user_task"
    assert restored["messages"][-1]["run_id"] == body["result"]["run_id"]
    assert any(item["run_id"] == body["result"]["run_id"] for item in tasks)


def test_jarvis_session_id_cannot_escape_session_store(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        response = client.get("/jarvis/sessions/..%2Foutside")
    # Starlette may reject the encoded slash before the endpoint validator runs.
    assert response.status_code in {400, 404}


def test_ux05_pause_uses_same_checkpoint_and_resume(monkeypatch, tmp_path: Path) -> None:
    from app.agents.researcher import FakeResearcher

    release = threading.Event()
    entered = threading.Event()
    original = FakeResearcher.run

    def delayed(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FakeResearcher, "run", delayed)
    result: dict[str, object] = {}

    def execute() -> None:
        result["report"] = run_task(
            "比较几个 Agent 项目",
            20_000,
            1.0,
            data_dir=tmp_path,
            model_mode="fake",
        )

    worker = threading.Thread(target=execute, daemon=True)
    worker.start()
    assert entered.wait(5)
    run_id = ""
    for _ in range(100):
        tasks = list_tasks(tmp_path)
        if tasks:
            run_id = tasks[0]["run_id"]
            break
        time.sleep(0.02)
    assert run_id
    TaskControlStore(tmp_path).request(run_id, "pause")
    release.set()
    worker.join(10)
    report = result["report"]
    assert report.status == "paused"  # type: ignore[union-attr]
    assert report.run_id == run_id  # type: ignore[union-attr]

    TaskControlStore(tmp_path).clear_action(run_id)
    resumed = resume_task(run_id, data_dir=tmp_path)
    assert resumed.status == "completed"
    assert len(list_tasks(tmp_path)) == 1


def test_ux07_stop_halts_at_next_safe_boundary(monkeypatch, tmp_path: Path) -> None:
    from app.agents.researcher import FakeResearcher

    release = threading.Event()
    entered = threading.Event()
    original = FakeResearcher.run

    def delayed(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FakeResearcher, "run", delayed)
    result: dict[str, object] = {}
    worker = threading.Thread(
        target=lambda: result.setdefault(
            "report", run_task("研究几个 Agent 项目", 20_000, 1.0, data_dir=tmp_path)
        ),
        daemon=True,
    )
    worker.start()
    assert entered.wait(5)
    run_id = ""
    for _ in range(100):
        tasks = list_tasks(tmp_path)
        if tasks:
            run_id = tasks[0]["run_id"]
            break
        time.sleep(0.02)
    assert run_id
    TaskControlStore(tmp_path).request(run_id, "stop")
    release.set()
    worker.join(10)
    assert result["report"].status == "paused"  # type: ignore[union-attr]
    assert TaskControlStore(tmp_path).snapshot(run_id)["action"] == "stop"


def test_ux14_session_restores_structured_recent_work(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/jarvis/sessions/jarvis-desktop/turns",
            json={"user_input": "你好", "model_mode": "fake"},
        ).json()
        restored = client.get("/jarvis/sessions/jarvis-desktop").json()
    assert restored["messages"] == created["session"]["messages"]
    assert len(restored["messages"]) == 2
    assert "claims" not in restored["messages"][1]


def test_ux19_minimal_interruption_never_changes_permission(
    tmp_path: Path, monkeypatch
) -> None:
    from app.security.permissions import PermissionStore

    PermissionStore(tmp_path).set_mode("maximum", changed_by_user=True, confirmed=True)
    with _client(tmp_path, monkeypatch) as client:
        response = client.put(
            "/settings/interaction",
            json={
                "mode": "minimal_interruption",
                "notify_completed": False,
                "notify_approval": True,
                "notify_failed": True,
                "changed_at": "",
            },
        )
        permission = client.get("/settings/security/permission-mode").json()
    assert response.status_code == 200
    assert response.json()["mode"] == "minimal_interruption"
    assert permission["mode"] == "maximum"


def test_ux20_computer_control_stays_off_by_default(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        status = client.get("/computer")
    assert status.status_code == 200
    assert status.json()["control"] == "off"
