from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app.api.server as server
from app.api.server import app


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    server._settings_cache = None
    return TestClient(app)


def test_freeze10_desktop_session_token_has_no_sixty_second_expiry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AI_TEAM_OS_DESKTOP_SESSION_TOKEN", "stable-session")
    with _client(tmp_path, monkeypatch) as client:
        assert client.get("/system/health").status_code == 401
        for _ in range(3):
            assert (
                client.get(
                    "/system/health", headers={"X-Desktop-Session": "stable-session"}
                ).status_code
                == 200
            )


def test_terminal_sse_event_is_a_complete_runtime_event(
    tmp_path: Path, monkeypatch
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/tasks", json={"goal": "github_compare_team", "model_mode": "fake"}
        ).json()
        response = client.get(f"/tasks/{created['run_id']}/events")
    frames = [item for item in response.text.split("\n\n") if "data:" in item]
    terminal = json.loads(frames[-1].split("data:", 1)[1].strip())
    assert terminal["event_type"] == "task_status_changed"
    assert terminal["payload_safe"]["status"] == "completed"
    assert terminal["event_id"]
    assert terminal["timestamp"]
    assert "ts" not in terminal and "status" not in terminal


def _frontend_sources() -> tuple[str, str, str]:
    root = Path(__file__).resolve().parents[1]
    client = (root / "web/src/api/client.ts").read_text(encoding="utf-8")
    hook = (root / "web/src/hooks/useEvents.ts").read_text(encoding="utf-8")
    feed = (root / "web/src/components/ActivityFeed.tsx").read_text(encoding="utf-8")
    return client, hook, feed


def test_freeze03_sse_reconnect_is_bounded() -> None:
    client, _, _ = _frontend_sources()
    assert "const backoff = [1000, 2000, 5000, 10000, 15000, 30000]" in client


def test_freeze04_event_source_cleanup() -> None:
    client, _, _ = _frontend_sources()
    assert "window.clearTimeout(retryTimer)" in client
    assert "abort?.abort()" in client


def test_freeze05_duplicate_events_are_ignored() -> None:
    client, _, _ = _frontend_sources()
    assert "seenIds.has(ev.event_id)" in client


def test_freeze06_large_event_burst_is_bounded() -> None:
    _, hook, _ = _frontend_sources()
    assert "MAX_VISIBLE_RUNTIME_EVENTS = 300" in hook
    assert ".slice(-MAX_VISIBLE_RUNTIME_EVENTS)" in hook


def test_freeze07_activity_list_is_bounded() -> None:
    _, _, feed = _frontend_sources()
    assert "events.slice(-300)" in feed


def test_freeze08_backend_recovery_is_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    desktop = (root / "src-tauri/src/main.rs").read_text(encoding="utf-8")
    assert "if attempt > 2" in desktop
    assert "backend_restart_exhausted" in desktop


def test_freeze01_react_root_has_recovery_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    main = (root / "web/src/main.tsx").read_text(encoding="utf-8")
    boundary = (root / "web/src/components/AppRootErrorBoundary.tsx").read_text(
        encoding="utf-8"
    )
    assert "<AppRootErrorBoundary><App /></AppRootErrorBoundary>" in main
    assert "RuntimeRecoveryView" in boundary


def test_freeze09_reload_does_not_create_or_cancel_task() -> None:
    root = Path(__file__).resolve().parents[1]
    recovery = (root / "web/src/components/RuntimeRecoveryView.tsx").read_text(
        encoding="utf-8"
    )
    assert "window.location.reload()" in recovery
    assert "createTask" not in recovery and "cancel" not in recovery.lower()


def test_freeze11_task_running_over_120_seconds_has_no_client_timeout() -> None:
    root = Path(__file__).resolve().parents[1]
    client = (root / "web/src/api/client.ts").read_text(encoding="utf-8")
    assert "60000" not in client and "120000" not in client


def test_freeze12_five_sequential_tasks_do_not_share_event_state() -> None:
    _, hook, _ = _frontend_sources()
    assert "ref.current = []" in hook
    assert "[runId, enabled]" in hook


def test_freeze13_listener_growth_is_bounded() -> None:
    client, _, _ = _frontend_sources()
    assert "closed = true" in client
    assert "return close" in Path(__file__).resolve().parents[1].joinpath(
        "web/src/hooks/useEvents.ts"
    ).read_text(encoding="utf-8")


def test_freeze14_frontend_event_store_is_bounded() -> None:
    _, hook, _ = _frontend_sources()
    assert "slice(-MAX_VISIBLE_RUNTIME_EVENTS)" in hook


def test_freeze15_unknown_route_has_nonblank_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    app = (root / "web/src/App.tsx").read_text(encoding="utf-8")
    assert '<Route path="*" element={<Navigate to="/" replace />} />' in app


def test_frontend_diagnostic_schema_is_content_minimal() -> None:
    root = Path(__file__).resolve().parents[1]
    diagnostic = (root / "web/src/runtime/diagnostics.ts").read_text(encoding="utf-8")
    for forbidden_field in ("api_key:", "password:", "prompt:", "assistant_content:", "reasoning:"):
        assert forbidden_field not in diagnostic.lower()
    assert "[redacted]" in diagnostic.lower()
