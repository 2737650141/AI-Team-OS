from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import app.api.server as server
from app.api.server import app
from app.runner import list_tasks, run_task
from app.security.permissions import (
    ActionDecision,
    ActionRequest,
    PermissionMode,
    PermissionPolicy,
    PermissionStore,
    RiskClass,
)


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    server._settings_cache = None
    return TestClient(app)


def test_hotfix01_maximum_hello_has_no_approval(tmp_path: Path, monkeypatch) -> None:
    PermissionStore(tmp_path).set_mode("maximum", changed_by_user=True, confirmed=True)
    with _client(tmp_path, monkeypatch) as client:
        response = client.post("/tasks", json={"goal": "你好", "model_mode": "fake"})
        detail = client.get(f"/tasks/{response.json()['run_id']}").json()
        approvals = client.get(f"/tasks/{response.json()['run_id']}/approvals").json()
        tasks = client.get("/tasks").json()
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["run_kind"] == "conversation"
    assert detail["pending_approval_id"] is None
    assert detail["pending_clarification_id"] is None
    assert approvals == []
    assert tasks == []


def test_hotfix02_standard_capability_chat_has_no_approval(tmp_path: Path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/tasks", json={"goal": "你可以干什么", "model_mode": "fake"}
        )
        detail = client.get(f"/tasks/{response.json()['run_id']}").json()
        tasks = client.get("/tasks").json()
    assert response.json()["status"] == "completed"
    assert response.json()["run_kind"] == "conversation"
    assert detail["pending_approval_id"] is None
    assert detail["pending_clarification_id"] is None
    assert tasks == []


def test_hotfix03_pure_conversation_never_builds_approval_service(
    tmp_path: Path, monkeypatch
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("ApprovalService must not be constructed for conversation")

    monkeypatch.setattr("app.core.approval.ApprovalService.__init__", forbidden)
    report = run_task(
        "你好", 10_000, 1.0, data_dir=tmp_path, run_kind="conversation"
    )
    assert report.status == "completed"
    assert report.tool_call_count == 0


def test_hotfix04_provider_probe_does_not_create_user_task(
    tmp_path: Path, monkeypatch
) -> None:
    from app.gateway.contracts import ModelResponse, UsageEstimate

    class DiagnosticProvider:
        provider_name = "Diagnostic Provider"

        def __init__(self, *args, **kwargs) -> None:
            pass

        def estimate_usage(self, request):
            return UsageEstimate(estimated_input_tokens=10, estimated_max_output_tokens=8)

        def generate(self, request):
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model=request.model,
                raw_text='{"status":"ok","number":7}',
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
                usage_source="REPORTED",
                latency_ms=3,
            )

    monkeypatch.setattr(
        "app.gateway.openai_compatible.OpenAICompatibleProvider", DiagnosticProvider
    )
    with _client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/settings/connections/providers",
            json={
                "provider_name": "Diagnostic Provider",
                "base_url": "https://8.8.8.8/v1",
                "default_model": "diagnostic-model",
                "is_default": True,
            },
        ).json()
        provider_id = created["provider_id"]
        client.put(
            f"/settings/connections/providers/{provider_id}/credential",
            json={"api_key": "test-only-key", "storage_mode": "session"},
        )
        response = client.post(
            f"/settings/connections/providers/{provider_id}/test-model",
            json={"model": "diagnostic-model"},
        )
        tasks = client.get("/tasks").json()
    assert response.status_code == 200
    assert response.json()["total_tokens"] == 18
    assert tasks == []


def test_hotfix05_diagnostic_usage_keeps_scope(tmp_path: Path) -> None:
    from app.usage.models import NormalizedModelUsage, UsageSource
    from app.usage.store import UsageStore

    store = UsageStore(tmp_path)
    store.record(
        NormalizedModelUsage(
            usage_id="u1",
            scope="diagnostic",
            task_id="diagnostic:model-test:1",
            run_id="diagnostic:model-test:1",
            call_id="c1",
            role="diagnostic",
            agent_id="provider_probe",
            provider_id="p",
            provider_name="p",
            model_id="m",
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
            usage_source=UsageSource.REPORTED,
        )
    )
    assert store.summary(task_id="diagnostic:model-test:1", days=None)["total_tokens"] == 7
    with store._connect() as conn:
        assert conn.execute("select scope from model_usage").fetchone()[0] == "diagnostic"


def test_hotfix06_legacy_diagnostic_is_hidden_from_tasks(tmp_path: Path) -> None:
    report = run_task("Reply with exactly: OK", 10_000, 1.0, data_dir=tmp_path)
    from app.usage.models import NormalizedModelUsage, UsageSource
    from app.usage.store import UsageStore

    store = UsageStore(tmp_path)
    store.record(
        NormalizedModelUsage(
            usage_id="legacy-u",
            task_id=report.task_id,
            run_id=report.run_id,
            call_id="legacy-c",
            role="planner",
            agent_id="planner",
            provider_id="p",
            provider_name="p",
            model_id="m",
            input_tokens=10,
            output_tokens=2,
            total_tokens=12,
            usage_source=UsageSource.REPORTED,
        )
    )
    assert all(item["goal"] != "Reply with exactly: OK" for item in list_tasks(tmp_path))
    with store._connect() as conn:
        assert conn.execute("select scope from model_usage").fetchone()[0] == "diagnostic"


def test_hotfix07_pending_normal_approval_resumes_after_maximum(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "AI_TEAM_ALLOWED_READ_ROOTS", str(Path(__file__).resolve().parent.parent / "fixtures")
    )
    PermissionStore(data_dir).set_mode("safe", changed_by_user=True)
    server._settings_cache = None
    with TestClient(app) as client:
        created = client.post(
            "/tasks",
            json={
                "goal": "sandbox_code_fix",
                "model_mode": "fake",
                "project_alias": "sample-python",
                "token_budget": 20_000,
            },
        ).json()
        assert created["status"] == "paused"
        before = client.get(f"/tasks/{created['run_id']}").json()
        assert before["pending_approval_id"]
        switched = client.put(
            "/settings/security/permission-mode",
            json={
                "mode": "maximum",
                "confirmed": True,
                "user_explicit_action": True,
            },
        )
        after = client.get(f"/tasks/{created['run_id']}").json()
    assert switched.status_code == 200
    assert after["current_status"] == "completed"
    assert after["pending_approval_id"] is None


def test_hotfix08_sensitive_confirmation_stays_ask() -> None:
    decision = PermissionPolicy().decide(
        PermissionMode.MAXIMUM,
        ActionRequest(action="payment", risk=RiskClass.SENSITIVE),
    )
    assert decision.decision is ActionDecision.ASK


def test_hotfix09_password_and_uac_stay_hard_bounded() -> None:
    policy = PermissionPolicy()
    for action in ("read_password_field", "bypass_uac"):
        decision = policy.decide(
            PermissionMode.MAXIMUM,
            ActionRequest(action=action, risk=RiskClass.FORBIDDEN),
        )
        assert decision.decision is ActionDecision.BLOCK


def test_hotfix10_normal_orchestration_remains_a_user_task(tmp_path: Path) -> None:
    report = run_task("github_compare_team", 10_000, 1.0, data_dir=tmp_path)
    assert report.state.run_kind == "user_task"
    assert report.status == "completed"
    assert report.state.pending_approval_id is None
