"""Real Windows acceptance for the M6-P permission-mode matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.security.permissions import PermissionRuntime, PermissionStore
from app.windows_control.backend import WindowsAutomationBackend
from app.windows_control.gateway import ActionError, ApprovalRequired, WindowsActionGateway
from app.windows_control.models import ActionRisk, ActionStep, SessionCapability
from app.windows_control.registry import ApplicationRegistry
from app.windows_control.session import DeviceSessionManager


def step(step_id: str, tool: str, risk: ActionRisk, **arguments: Any) -> ActionStep:
    return ActionStep(
        step_id=step_id,
        tool=tool,
        risk=risk,
        arguments=arguments,
        rationale=step_id,
        expected_state="re-observed",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    store = PermissionStore(args.data_dir)
    runtime = PermissionRuntime(store)
    backend = WindowsAutomationBackend()
    sessions = DeviceSessionManager()
    gateway = WindowsActionGateway(
        sessions,
        backend,
        ApplicationRegistry(project_root),
        runtime,
    )
    sessions.start(user_id="m6p-acceptance", capability=SessionCapability.LOW_RISK_CONTROL)
    results: dict[str, Any] = {}
    window_id = ""
    try:
        fixture, _ = gateway.execute(
            step("launch", "windows_launch_app", ActionRisk.LOW, app_id="test_fixture"),
            task_id="m6p-real",
        )
        window_id = fixture.window_id
        elements = backend.accessibility_tree(window_id)
        textbox = next(
            item for item in elements if item.control_type.lower() == "edit" and not item.password
        )
        password = next(item for item in elements if item.password)

        store.set_mode("safe", changed_by_user=True)
        try:
            gateway.execute(
                step(
                    "safe-text",
                    "windows_set_text",
                    ActionRisk.MEDIUM,
                    window_id=window_id,
                    element_id=textbox.element_id,
                    text="SAFE must ask",
                ),
                task_id="m6p-real",
            )
            safe_asked = False
        except ApprovalRequired:
            safe_asked = True
        results["safe"] = {"approval_required": safe_asked}

        store.set_mode("standard", changed_by_user=True)
        standard, _ = gateway.execute(
            step(
                "standard-text",
                "windows_set_text",
                ActionRisk.MEDIUM,
                window_id=window_id,
                element_id=textbox.element_id,
                text="STANDARD automatic",
            ),
            task_id="m6p-real",
        )
        results["standard"] = {
            "approval_required": False,
            "characters": standard["characters"],
        }

        store.set_mode("maximum", changed_by_user=True, confirmed=True)
        maximum, _ = gateway.execute(
            step(
                "maximum-text",
                "windows_set_text",
                ActionRisk.MEDIUM,
                window_id=window_id,
                element_id=textbox.element_id,
                text="MAXIMUM automatic",
            ),
            task_id="m6p-real",
        )
        results["maximum"] = {
            "approval_required": False,
            "characters": maximum["characters"],
        }

        try:
            gateway.execute(
                step(
                    "password",
                    "windows_set_text",
                    ActionRisk.MEDIUM,
                    window_id=window_id,
                    element_id=password.element_id,
                    text="must-not-write",
                ),
                task_id="m6p-real",
            )
            password_blocked = False
        except ActionError as exc:
            password_blocked = exc.code == "credential_field_forbidden"
        results["password"] = {"blocked": password_blocked}

        original_uac_check = backend.has_elevation_prompt
        backend.has_elevation_prompt = lambda: True  # type: ignore[method-assign]
        try:
            gateway.execute(
                step("uac", "windows_get_active_window", ActionRisk.OBSERVE),
                task_id="m6p-real",
            )
            uac_blocked = False
        except ActionError as exc:
            uac_blocked = exc.code == "ELEVATION_REQUIRED"
        finally:
            backend.has_elevation_prompt = original_uac_check  # type: ignore[method-assign]
        results["uac"] = {"blocked": uac_blocked, "status": "ELEVATION_REQUIRED"}

        sessions.start(user_id="m6p-acceptance", capability=SessionCapability.LOW_RISK_CONTROL)
        sessions.terminate()
        try:
            gateway.execute(
                step("stop", "windows_get_active_window", ActionRisk.OBSERVE),
                task_id="m6p-real",
            )
            stop_blocked = False
        except ActionError as exc:
            stop_blocked = exc.code == "action_after_stop"
        results["stop"] = {"blocked": stop_blocked}
    finally:
        if window_id:
            try:
                sessions.start(
                    user_id="m6p-acceptance", capability=SessionCapability.LOW_RISK_CONTROL
                )
                store.set_mode("maximum", changed_by_user=True, confirmed=True)
                gateway.execute(
                    step(
                        "cleanup",
                        "windows_close_window",
                        ActionRisk.HIGH,
                        window_id=window_id,
                    ),
                    task_id="m6p-real",
                )
            except Exception:
                pass

    passed = all(
        (
            results.get("safe", {}).get("approval_required"),
            not results.get("standard", {}).get("approval_required", True),
            not results.get("maximum", {}).get("approval_required", True),
            results.get("password", {}).get("blocked"),
            results.get("uac", {}).get("blocked"),
            results.get("stop", {}).get("blocked"),
        )
    )
    results["summary"] = {"passed": passed, "real_windows": True}
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
