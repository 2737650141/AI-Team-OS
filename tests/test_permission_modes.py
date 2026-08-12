from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.server import app
from app.gateway.audit import AuditLog
from app.gateway.tool_gateway import ToolGateway
from app.security.permissions import (
    ActionDecision,
    ActionRequest,
    PermissionChangeError,
    PermissionMode,
    PermissionPolicy,
    PermissionRuntime,
    PermissionStore,
    RiskClass,
    RiskClassifier,
)
from app.tools.spec import RiskLevel, ToolSpec
from app.windows_control.gateway import ActionError, WindowsActionGateway
from app.windows_control.models import ActionRisk, ActionStep, SessionCapability
from app.windows_control.registry import ApplicationRegistry
from tests.test_windows_action_layer import FakeBackend


def registry(tmp_path: Path) -> ApplicationRegistry:
    return ApplicationRegistry(tmp_path)


def decide(mode: PermissionMode, risk: RiskClass, **kwargs) -> ActionDecision:
    request = ActionRequest(action="fixture", risk=risk, **kwargs)
    return PermissionPolicy().decide(mode, request).decision


def test_gt_perm01_safe_readonly_auto() -> None:
    assert decide(PermissionMode.SAFE, RiskClass.READ_ONLY) is ActionDecision.ALLOW


def test_gt_perm02_safe_write_asks() -> None:
    assert decide(PermissionMode.SAFE, RiskClass.NORMAL) is ActionDecision.ASK


def test_gt_perm03_standard_normal_write_auto() -> None:
    assert decide(PermissionMode.STANDARD, RiskClass.NORMAL) is ActionDecision.ALLOW


def test_gt_perm04_standard_code_patch_auto() -> None:
    request = ActionRequest(action="apply_patch", risk=RiskClass.NORMAL)
    assert PermissionPolicy().decide(PermissionMode.STANDARD, request).decision == "allow"


def test_gt_perm05_standard_test_auto() -> None:
    request = ActionRequest(action="run_tests", risk=RiskClass.NORMAL)
    assert PermissionPolicy().decide(PermissionMode.STANDARD, request).decision == "allow"


def test_gt_perm06_standard_destructive_asks() -> None:
    assert decide(PermissionMode.STANDARD, RiskClass.DESTRUCTIVE) is ActionDecision.ASK


def test_gt_perm07_maximum_write_auto() -> None:
    assert decide(PermissionMode.MAXIMUM, RiskClass.NORMAL) is ActionDecision.ALLOW


def test_gt_perm08_maximum_delete_auto() -> None:
    assert decide(PermissionMode.MAXIMUM, RiskClass.DESTRUCTIVE) is ActionDecision.ALLOW


def test_gt_perm09_maximum_windows_action_auto(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    store.set_mode(PermissionMode.MAXIMUM, changed_by_user=True, confirmed=True)
    from app.windows_control.session import DeviceSessionManager

    sessions = DeviceSessionManager()
    sessions.start(user_id="local-user", capability=SessionCapability.LOW_RISK_CONTROL)
    backend = FakeBackend()
    gateway = WindowsActionGateway(
        sessions, backend, registry(tmp_path), PermissionRuntime(store)
    )
    assert gateway.needs_approval("windows_set_text") is False


def test_gt_perm10_maximum_explicit_external_action_auto() -> None:
    assert decide(
        PermissionMode.MAXIMUM, RiskClass.EXTERNAL_EFFECT, task_explicit=True
    ) is ActionDecision.ALLOW
    assert decide(
        PermissionMode.MAXIMUM, RiskClass.EXTERNAL_EFFECT, task_explicit=False
    ) is ActionDecision.ASK


def test_maximum_purchase_is_a_sensitive_final_confirmation() -> None:
    assert RiskClassifier.classify("submit_payment") is RiskClass.SENSITIVE
    request = ActionRequest(
        action="submit_payment",
        risk=RiskClass.SENSITIVE,
        task_explicit=True,
    )
    assert PermissionPolicy().decide(PermissionMode.MAXIMUM, request).decision is ActionDecision.ASK


def test_gt_perm11_maximum_secret_extraction_blocked() -> None:
    request = ActionRequest(action="extract_secret", risk=RiskClass.FORBIDDEN)
    assert PermissionPolicy().decide(PermissionMode.MAXIMUM, request).decision == "block"


def test_gt_perm12_maximum_uac_bypass_blocked(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    store.set_mode("maximum", changed_by_user=True, confirmed=True)
    from app.windows_control.session import DeviceSessionManager

    sessions = DeviceSessionManager()
    sessions.start(user_id="local-user", capability=SessionCapability.LOW_RISK_CONTROL)
    backend = FakeBackend()
    backend.elevation = True
    gateway = WindowsActionGateway(
        sessions, backend, registry(tmp_path), PermissionRuntime(store)
    )
    with pytest.raises(ActionError, match="UAC elevation") as caught:
        gateway.execute(
            ActionStep(
                step_id="uac",
                tool="windows_focus_window",
                arguments={"window_id": "window-1"},
                risk=ActionRisk.LOW,
            ),
            task_id="t1",
        )
    assert caught.value.code == "ELEVATION_REQUIRED"


def test_gt_perm13_prompt_injection_cannot_change_mode(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    with pytest.raises(PermissionChangeError):
        store.set_mode("maximum", changed_by_user=True, confirmed=True, source="web_content")
    assert store.mode() is PermissionMode.STANDARD


def test_gt_perm14_model_cannot_change_mode(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    with pytest.raises(PermissionChangeError):
        store.set_mode("maximum", changed_by_user=False, confirmed=True, source="agent")


def test_gt_perm15_mode_survives_restart(tmp_path: Path) -> None:
    PermissionStore(tmp_path).set_mode("safe", changed_by_user=True)
    assert PermissionStore(tmp_path).mode() is PermissionMode.SAFE


def test_gt_perm16_mode_applies_new_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    PermissionStore(tmp_path).set_mode("safe", changed_by_user=True)
    with TestClient(app) as client:
        response = client.post(
            "/tasks",
            json={"goal": "github_compare_team", "model_mode": "fake"},
        )
    assert response.status_code == 200
    assert response.json()["permission_mode"] == "safe"


def test_gt_perm17_max_to_safe_affects_running_gateway(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    store.set_mode("maximum", changed_by_user=True, confirmed=True)
    gateway = ToolGateway(
        AuditLog(tmp_path / "audit.jsonl"),
        "running-task",
        permission_runtime=PermissionRuntime(store),
    )
    calls: list[str] = []
    gateway.register(
        ToolSpec(
            name="normal_write",
            description="fixture",
            input_schema={},
            risk_level=RiskLevel.SENSITIVE,
            read_only=False,
            requires_approval=True,
            permission_risk="normal",
            handler=lambda: calls.append("first"),
        )
    )
    assert gateway.invoke("normal_write", {}).ok is True
    store.set_mode("safe", changed_by_user=True)
    gateway.register(
        ToolSpec(
            name="second_normal_write",
            description="fixture",
            input_schema={},
            risk_level=RiskLevel.SENSITIVE,
            read_only=False,
            requires_approval=True,
            permission_risk="normal",
            handler=lambda: calls.append("second"),
        )
    )
    assert gateway.invoke("second_normal_write", {}).status == "blocked"
    assert calls == ["first"]


def test_gt_perm18_stop_unaffected() -> None:
    for mode in PermissionMode:
        request = ActionRequest(action="bypass_stop", risk=RiskClass.FORBIDDEN)
        assert PermissionPolicy().decide(mode, request).decision is ActionDecision.BLOCK


def test_gt_perm19_computer_control_session_still_required(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    store.set_mode("maximum", changed_by_user=True, confirmed=True)
    from app.windows_control.session import DeviceSessionManager

    gateway = WindowsActionGateway(
        DeviceSessionManager(), FakeBackend(), registry(tmp_path), PermissionRuntime(store)
    )
    with pytest.raises(ActionError):
        gateway.execute(
            ActionStep(
                step_id="no-session",
                tool="windows_focus_window",
                risk=ActionRisk.LOW,
            ),
            task_id="t1",
        )


def test_gt_perm20_audit_records_auto_actions(tmp_path: Path) -> None:
    store = PermissionStore(tmp_path)
    runtime = PermissionRuntime(store)
    result = runtime.decide(
        ActionRequest(
            action="apply_patch",
            risk=RiskClass.NORMAL,
            target="app/core/router.py",
            task_id="t-audit",
        )
    )
    assert result.decision is ActionDecision.ALLOW
    history = store.recent()
    assert history[0].action == "apply_patch"
    assert history[0].permission_mode is PermissionMode.STANDARD
    assert history[0].decision is ActionDecision.ALLOW


def test_permission_api_requires_explicit_user_action_and_one_time_maximum_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AI_TEAM_OS_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/settings/security/permission-mode").json()["mode"] == "standard"
        denied = client.put(
            "/settings/security/permission-mode",
            json={"mode": "maximum", "confirmed": True, "user_explicit_action": False},
        )
        assert denied.status_code == 409
        first = client.put(
            "/settings/security/permission-mode",
            json={"mode": "maximum", "confirmed": False, "user_explicit_action": True},
        )
        assert first.status_code == 409
        enabled = client.put(
            "/settings/security/permission-mode",
            json={"mode": "maximum", "confirmed": True, "user_explicit_action": True},
        )
        assert enabled.status_code == 200
        assert enabled.json()["maximum_confirmed"] is True
        client.put(
            "/settings/security/permission-mode",
            json={"mode": "standard", "user_explicit_action": True},
        )
        again = client.put(
            "/settings/security/permission-mode",
            json={"mode": "maximum", "user_explicit_action": True},
        )
        assert again.status_code == 200
