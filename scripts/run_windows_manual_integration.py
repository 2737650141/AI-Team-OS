"""Manual M5-A Windows integration acceptance. Not part of normal CI.

This script deliberately saves only explicitly requested test-window screenshots when
--evidence-dir is provided. General desktop captures remain in memory and are discarded.
"""

from __future__ import annotations

import argparse
import base64
import faulthandler
import json
from pathlib import Path
from typing import Any

from app.windows_control.backend import WindowsAutomationBackend
from app.windows_control.gateway import ActionError, WindowsActionGateway
from app.windows_control.models import ActionRisk, ActionStep, SessionCapability
from app.windows_control.registry import ApplicationRegistry
from app.windows_control.session import DeviceSessionManager


def step(step_id: str, tool: str, risk: ActionRisk, **arguments: Any) -> ActionStep:
    return ActionStep(
        step_id=step_id,
        tool=tool,
        arguments=arguments,
        rationale=step_id,
        expected_state="re-observed",
        risk=risk,
    )


def save_frame(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(frame.image_base64))


def main() -> int:
    faulthandler.enable()
    faulthandler.dump_traceback_later(30, repeat=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    progress_path = args.json_output.with_suffix(".progress.txt") if args.json_output else None

    def mark(message: str) -> None:
        print(message, flush=True)
        if progress_path:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")

    project_root = Path(__file__).resolve().parents[1]
    backend = WindowsAutomationBackend()
    sessions = DeviceSessionManager()
    registry = ApplicationRegistry(project_root)
    gateway = WindowsActionGateway(sessions, backend, registry)
    sessions.start(user_id="m5a-acceptance", capability=SessionCapability.LOW_RISK_CONTROL)
    results: dict[str, Any] = {}

    active, _ = gateway.execute(
        step("GT-WIN01", "windows_get_active_window", ActionRisk.OBSERVE),
        task_id="gt-win",
    )
    results["GT-WIN01"] = {"pass": active is not None, "title": active.title if active else ""}
    mark("GT-WIN01 complete")

    windows, _ = gateway.execute(
        step("GT-WIN02", "windows_list_windows", ActionRisk.OBSERVE),
        task_id="gt-win",
    )
    results["GT-WIN02"] = {"pass": len(windows) > 0, "count": len(windows)}
    mark("GT-WIN02 complete")

    notepad, _ = gateway.execute(
        step("GT-WIN03", "windows_launch_app", ActionRisk.LOW, app_id="notepad"),
        task_id="gt-win",
    )
    results["GT-WIN03"] = {"pass": bool(backend.get_window_info(notepad.window_id))}
    mark("GT-WIN03 complete")
    if args.evidence_dir:
        save_frame(
            backend.capture_window(notepad.window_id), args.evidence_dir / "notepad-launch.png"
        )

    typed, _ = gateway.execute(
        step(
            "GT-WIN04",
            "windows_set_text",
            ActionRisk.MEDIUM,
            window_id=notepad.window_id,
            text="AI Team OS Windows Control Test",
        ),
        task_id="gt-win",
        approved=True,
    )
    results["GT-WIN04"] = {"pass": typed["characters"] == 31, "saved": False}
    mark("GT-WIN04 complete")
    if args.evidence_dir:
        save_frame(
            backend.capture_window(notepad.window_id), args.evidence_dir / "notepad-typed.png"
        )

    browser = next(
        (
            item
            for item in backend.list_windows()
            if "edge" in item.title.lower() or "browser" in item.title.lower()
        ),
        None,
    )
    if browser is not None:
        backend.focus_window(notepad.window_id)
        backend.focus_window(browser.window_id)
        final_focus = backend.focus_window(notepad.window_id)
        switch_pass = final_focus.window_id == notepad.window_id
    else:
        switch_pass = False
    results["GT-WIN05"] = {"pass": switch_pass}
    mark("GT-WIN05 complete")

    fixture, _ = gateway.execute(
        step("GT-WIN06-launch", "windows_launch_app", ActionRisk.LOW, app_id="test_fixture"),
        task_id="gt-win",
    )
    mark("GT-WIN06 fixture launched")
    button = backend.find_element(
        fixture.window_id, control_types=("Button",), name="Fixture Action"
    )
    mark("GT-WIN06 button found")
    gateway.execute(
        step(
            "GT-WIN06-click",
            "windows_click_element",
            ActionRisk.MEDIUM,
            window_id=fixture.window_id,
            element_id=button.element_id,
        ),
        task_id="gt-win",
        approved=True,
    )
    mark("GT-WIN06 button clicked")
    textbox = next(
        item
        for item in backend.accessibility_tree(fixture.window_id)
        if item.control_type.lower() == "edit" and not item.password
    )
    mark("GT-WIN06 textbox found")
    gateway.execute(
        step(
            "GT-WIN06-text",
            "windows_set_text",
            ActionRisk.MEDIUM,
            window_id=fixture.window_id,
            element_id=textbox.element_id,
            text="Fixture text",
        ),
        task_id="gt-win",
        approved=True,
    )
    mark("GT-WIN06 text set")
    checkbox = backend.find_element(fixture.window_id, control_types=("CheckBox",))
    mark("GT-WIN06 checkbox found")
    gateway.execute(
        step(
            "GT-WIN06-check",
            "windows_click_element",
            ActionRisk.MEDIUM,
            window_id=fixture.window_id,
            element_id=checkbox.element_id,
        ),
        task_id="gt-win",
        approved=True,
    )
    mark("GT-WIN06 checkbox clicked")
    combo = backend.find_element(fixture.window_id, control_types=("ComboBox",))
    mark("GT-WIN06 combo found")
    gateway.execute(
        step(
            "GT-WIN06-select",
            "windows_click_element",
            ActionRisk.MEDIUM,
            window_id=fixture.window_id,
            element_id=combo.element_id,
            action="select",
            value="Beta",
        ),
        task_id="gt-win",
        approved=True,
    )
    mark("GT-WIN06 combo selected")
    checkbox_state = backend.element_state(fixture.window_id, checkbox.element_id)
    combo_state = backend.element_state(fixture.window_id, combo.element_id)
    list_item = backend.find_element(
        fixture.window_id, control_types=("ListItem",), name="Two"
    )
    mark("GT-WIN06 list item found")
    gateway.execute(
        step(
            "GT-WIN06-list",
            "windows_click_element",
            ActionRisk.MEDIUM,
            window_id=fixture.window_id,
            element_id=list_item.element_id,
        ),
        task_id="gt-win",
        approved=True,
    )
    mark("GT-WIN06 list selected")
    list_state = backend.element_state(fixture.window_id, list_item.element_id)
    results["GT-WIN06"] = {
        "pass": (
            "Fixture text" in backend.read_element_text(fixture.window_id, textbox.element_id)
            and checkbox_state.get("toggle_state") == 1
            and combo_state.get("selected_text") == "Beta"
            and list_state.get("selected") is True
        ),
        "accessibility_only": True,
    }
    mark("GT-WIN06 complete")
    if args.evidence_dir:
        save_frame(
            backend.capture_window(fixture.window_id), args.evidence_dir / "fixture-complete.png"
        )

    old_screen = backend.capture_screen()
    old_window = backend.get_window_info(fixture.window_id)
    backend.focus_window(notepad.window_id)
    try:
        gateway.execute(
            step(
                "GT-WIN07",
                "windows_click_coordinate",
                ActionRisk.HIGH,
                window_id=fixture.window_id,
                accessibility_unavailable=True,
                window_hash=old_window.window_hash,
                screenshot_hash=old_screen.screenshot_hash,
                screen_bounds=old_screen.bounds.model_dump(),
                x=old_window.bounds.left + 20,
                y=old_window.bounds.top + 20,
            ),
            task_id="gt-win",
            approved=True,
        )
        stale_blocked = False
    except ActionError as exc:
        stale_blocked = exc.code in {"window_not_active", "coordinate_stale"}
    results["GT-WIN07"] = {"pass": stale_blocked}
    mark("GT-WIN07 complete")

    password = next(item for item in backend.accessibility_tree(fixture.window_id) if item.password)
    try:
        gateway.execute(
            step(
                "GT-WIN08",
                "windows_set_text",
                ActionRisk.MEDIUM,
                window_id=fixture.window_id,
                element_id=password.element_id,
                text="must-not-write",
            ),
            task_id="gt-win",
            approved=True,
        )
        password_blocked = False
    except ActionError as exc:
        password_blocked = exc.code == "credential_field_forbidden"
    results["GT-WIN08"] = {"pass": password_blocked, "status": "FORBIDDEN"}
    mark("GT-WIN08 complete")

    original_uac_check = backend.has_elevation_prompt
    backend.has_elevation_prompt = lambda: True  # type: ignore[method-assign]
    try:
        gateway.execute(
            step("GT-WIN09", "windows_get_active_window", ActionRisk.OBSERVE),
            task_id="gt-win",
        )
        uac_blocked = False
    except ActionError as exc:
        uac_blocked = exc.code == "ELEVATION_REQUIRED"
    finally:
        backend.has_elevation_prompt = original_uac_check  # type: ignore[method-assign]
    results["GT-WIN09"] = {"pass": uac_blocked, "status": "ELEVATION_REQUIRED"}
    mark("GT-WIN09 complete")

    sessions.start(user_id="m5a-acceptance", capability=SessionCapability.LOW_RISK_CONTROL)
    sessions.terminate()
    try:
        gateway.execute(
            step("GT-WIN10", "windows_get_active_window", ActionRisk.OBSERVE),
            task_id="gt-win",
        )
        stopped = False
    except ActionError as exc:
        stopped = exc.code == "action_after_stop"
    results["GT-WIN10"] = {"pass": stopped}
    mark("GT-WIN10 complete")

    results["summary"] = {
        "passed": sum(bool(value.get("pass")) for value in results.values()),
        "total": 10,
        "screenshots": "explicit fixture/notepad evidence" if args.evidence_dir else "none",
    }
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    print(payload)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    return 0 if results["summary"]["passed"] == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
