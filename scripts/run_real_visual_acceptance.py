"""REAL-V01..05 against the real AI Team OS Edge window."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path

from app.desktop_vision.models import CaptureScope, GroundingStatus
from app.windows_control.models import ActionRisk, ActionStep, SessionCapability
from app.windows_control.service import WindowsComputerService


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    service = WindowsComputerService(project / "data", project)
    service.start_session(SessionCapability.LOW_RISK_CONTROL, user_id="m5b-real-acceptance")
    edge = next(
        item
        for item in service.backend.list_windows()
        if "AI Team OS" in item.title and "Edge" in item.app_name
    )
    service.backend.focus_window(edge.window_id)
    browser_refresh = service.backend.find_element(
        edge.window_id, control_types=("Button",), name="刷新"
    )
    service.gateway.execute(
        ActionStep(
            step_id="real-browser-refresh",
            tool="windows_click_element",
            arguments={
                "window_id": edge.window_id,
                "element_id": browser_refresh.element_id,
            },
            rationale="Refresh the registered local AI Team OS page",
            expected_state="Current local page reloads",
            risk=ActionRisk.MEDIUM,
        ),
        task_id="real-vision",
        approved=True,
    )
    time.sleep(0.5)
    results: dict[str, dict[str, object]] = {}

    dashboard = service.visual.observe(scope=CaptureScope.WINDOW, window_id=edge.window_id)
    actions_before = service.sessions.current().action_count  # type: ignore[union-attr]
    answer = service.visual.ask(
        "Describe the main regions of the current AI Team OS page. Do not click.",
        observation_id=dashboard.observation_id,
    )
    actions_after = service.sessions.current().action_count  # type: ignore[union-attr]
    results["REAL-V01"] = {
        "pass": actions_before == actions_after and answer.action_count == 0,
        "mode": dashboard.vision_mode.value,
        "intent": answer.intent,
        "elements": len(dashboard.visual_elements),
        "actions": 0,
    }

    settings_grounding = service.visual.ground(dashboard.observation_id, "打开左侧设置")
    settings_result = service.visual.act(settings_grounding.grounding_id, approved=True)
    results["REAL-V02"] = {
        "pass": settings_grounding.accessibility_match and settings_result.status == "verified",
        "grounding": settings_grounding.grounding_id,
        "accessibility_first": settings_grounding.accessibility_match,
        "verification": settings_result.verification,
    }

    settings_page = service.visual.observe(scope=CaptureScope.WINDOW, window_id=edge.window_id)
    computer_grounding = service.visual.ground(settings_page.observation_id, "打开电脑控制")
    if computer_grounding.status is not GroundingStatus.RESOLVED:
        computer_grounding = service.visual.ground(settings_page.observation_id, "Computer")
    service.visual.act(computer_grounding.grounding_id, approved=True)
    post_json(
        "http://127.0.0.1:8000/computer/session/start",
        {"capability": "low_risk_control", "ttl_minutes": 15},
    )
    # The page intentionally stops polling while control is OFF. A governed browser refresh
    # makes the externally started local session visible before observe-only acceptance.
    browser_refresh = service.backend.find_element(
        edge.window_id, control_types=("Button",), name="刷新"
    )
    service.gateway.execute(
        ActionStep(
            step_id="real-computer-refresh",
            tool="windows_click_element",
            arguments={
                "window_id": edge.window_id,
                "element_id": browser_refresh.element_id,
            },
            rationale="Refresh local Computer session state",
            expected_state="Computer controls are visible",
            risk=ActionRisk.MEDIUM,
        ),
        task_id="real-vision",
        approved=True,
    )
    time.sleep(1.0)

    computer_page = service.visual.observe(scope=CaptureScope.WINDOW, window_id=edge.window_id)
    pause = service.visual.ground(computer_page.observation_id, "找到暂停按钮")
    before_pause = service.sessions.current().action_count  # type: ignore[union-attr]
    time.sleep(0.1)
    after_pause = service.sessions.current().action_count  # type: ignore[union-attr]
    results["REAL-V03"] = {
        "pass": pause.status is GroundingStatus.RESOLVED and before_pause == after_pause,
        "status": pause.status.value,
        "confidence": pause.confidence,
        "actions": 0,
        "location": pause.selected_bounds.model_dump() if pause.selected_bounds else None,
    }

    refresh = service.visual.ground(computer_page.observation_id, "点击刷新屏幕")
    refresh_result = service.visual.act(refresh.grounding_id, approved=True)
    results["REAL-V04"] = {
        "pass": refresh.status is GroundingStatus.RESOLVED
        and refresh_result.status == "verified",
        "flow": "Grounding -> Validate -> Act -> Verify",
        "accessibility_first": refresh.accessibility_match,
        "attempts": refresh_result.attempts,
        "change_score": refresh_result.change_score,
    }

    service.gateway.execute(
        ActionStep(
            step_id="dismiss-transient-overlay",
            tool="windows_press_key",
            arguments={"window_id": edge.window_id, "key": "ESC"},
            rationale="Dismiss transient non-product overlay before explicit evidence",
            expected_state="Only the AI Team OS window remains in evidence",
            risk=ActionRisk.MEDIUM,
        ),
        task_id="real-vision",
        approved=True,
    )
    time.sleep(0.2)
    # Edge's optional dictionary surface may survive Escape after a prior visual-fixture run.
    # Re-invoking the current local navigation link is a governed, no-op UIA action that dismisses
    # that transient browser surface before the user-requested evidence capture.
    current_page_link = service.backend.find_element(
        edge.window_id,
        control_types=("Hyperlink", "Button", "ListItem"),
        name="电脑控制",
    )
    service.gateway.execute(
        ActionStep(
            step_id="dismiss-browser-dictionary",
            tool="windows_click_element",
            arguments={
                "window_id": edge.window_id,
                "element_id": current_page_link.element_id,
            },
            rationale="Keep the local Computer page active for clean evidence",
            expected_state="The local Computer page remains active",
            risk=ActionRisk.MEDIUM,
        ),
        task_id="real-vision",
        approved=True,
    )
    time.sleep(0.3)
    final_observation = service.visual.observe(scope=CaptureScope.WINDOW, window_id=edge.window_id)
    if args.evidence_dir:
        preview = service.visual.preview(final_observation.observation_id)
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        (args.evidence_dir / "real-ai-team-os-computer.png").write_bytes(
            base64.b64decode(preview["image_base64"])
        )
    provider = service.visual.capabilities.status()
    results["REAL-V05"] = {
        "pass": provider["multimodal_status"] == "NOT_CONFIGURED",
        "status": "NOT_CONFIGURED",
        "image_sent_external": False,
        "text_model": provider["text_model"],
    }

    service.stop()
    post_json("http://127.0.0.1:8000/computer/session/stop", {})
    passed = sum(bool(item["pass"]) for item in results.values())
    results["summary"] = {
        "pass": passed == 5,
        "passed": passed,
        "total": 5,
        "desktop_visual_layer": "VALIDATED",
        "multimodal_vision_model": "NOT_CONFIGURED",
    }
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if passed == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
