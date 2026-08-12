from __future__ import annotations

import uuid
from typing import Any

from app.security.permissions import (
    ActionDecision,
    ActionRequest,
    PermissionPolicy,
    PermissionRuntime,
    RiskClass,
)
from app.windows_control.backend import AutomationError, WindowsAutomationBackend
from app.windows_control.models import ActionRecord, ActionRisk, ActionStep, Bounds, PendingAction
from app.windows_control.registry import ApplicationRegistry, RegistryError
from app.windows_control.session import DeviceSessionManager, SessionError

OBSERVE_TOOLS = {
    "windows_get_active_window",
    "windows_list_windows",
    "windows_get_window_info",
    "windows_capture_screen",
    "windows_capture_window",
    "windows_get_accessibility_tree",
}

RISK_BY_TOOL = {
    **{tool: ActionRisk.OBSERVE for tool in OBSERVE_TOOLS},
    "windows_launch_app": ActionRisk.LOW,
    "windows_focus_window": ActionRisk.LOW,
    "windows_open_safe_path": ActionRisk.LOW,
    "windows_click_element": ActionRisk.MEDIUM,
    "windows_set_text": ActionRisk.MEDIUM,
    "windows_press_key": ActionRisk.MEDIUM,
    "windows_click_coordinate": ActionRisk.HIGH,
    "windows_close_window": ActionRisk.HIGH,
}


class ActionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApprovalRequired(ActionError):
    def __init__(self, pending: PendingAction) -> None:
        super().__init__("approval_required", pending.summary)
        self.pending = pending


class WindowsActionGateway:
    """The only authority allowed to call the Windows backend."""

    def __init__(
        self,
        sessions: DeviceSessionManager,
        backend: WindowsAutomationBackend,
        registry: ApplicationRegistry,
        permission_runtime: PermissionRuntime | None = None,
    ) -> None:
        self.sessions = sessions
        self.backend = backend
        self.registry = registry
        self.permission_runtime = permission_runtime

    def risk_for(self, tool: str) -> ActionRisk:
        risk = RISK_BY_TOOL.get(tool)
        if risk is None:
            raise ActionError("tool_unavailable", f"Windows tool is unavailable: {tool}")
        return risk

    def needs_approval(self, tool: str) -> bool:
        session = self.sessions.require_active(tool)
        risk = self.risk_for(tool)
        if risk is ActionRisk.OBSERVE:
            return False
        if session.capability.value == "observe_only":
            raise ActionError("permission_denied", "Observe-only session blocks write actions")
        decision = self._permission_decision(tool)
        if decision is ActionDecision.BLOCK:
            raise ActionError("hard_safety_block", "Hard Safety Kernel blocked this action")
        if session.capability.value == "ask_every_action":
            return True
        return decision is ActionDecision.ASK

    def _permission_decision(self, tool: str) -> ActionDecision:
        risk = {
            ActionRisk.OBSERVE: RiskClass.READ_ONLY,
            ActionRisk.LOW: RiskClass.LOW,
            ActionRisk.MEDIUM: RiskClass.NORMAL,
            ActionRisk.HIGH: RiskClass.DESTRUCTIVE,
            ActionRisk.FORBIDDEN: RiskClass.FORBIDDEN,
        }[self.risk_for(tool)]
        request = ActionRequest(
            action=tool,
            risk=risk,
            source="windows_action_gateway",
        )
        if self.permission_runtime is not None:
            return self.permission_runtime.decide(request).decision
        return PermissionPolicy().decide("safe", request).decision

    def explain(self, tool: str) -> dict[str, str]:
        risk = {
            ActionRisk.OBSERVE: RiskClass.READ_ONLY,
            ActionRisk.LOW: RiskClass.LOW,
            ActionRisk.MEDIUM: RiskClass.NORMAL,
            ActionRisk.HIGH: RiskClass.DESTRUCTIVE,
            ActionRisk.FORBIDDEN: RiskClass.FORBIDDEN,
        }[self.risk_for(tool)]
        request = ActionRequest(action=tool, risk=risk, source="windows_action_gateway")
        decision = (
            self.permission_runtime.decide(request, record=False)
            if self.permission_runtime is not None
            else PermissionPolicy().decide("safe", request)
        )
        return decision.model_dump(mode="json")

    def execute(
        self,
        step: ActionStep,
        *,
        task_id: str,
        approved: bool = False,
    ) -> tuple[Any, ActionRecord]:
        try:
            self.sessions.require_active(step.tool)
            if self.backend.is_locked():
                self.sessions.pause()
                raise ActionError("windows_session_locked", "Windows is locked; control paused")
            if self.backend.has_elevation_prompt():
                self.sessions.terminate()
                raise ActionError("ELEVATION_REQUIRED", "UAC elevation detected; control stopped")
            risk = self.risk_for(step.tool)
            if self.needs_approval(step.tool) and not approved:
                display_args = self._display_arguments(step)
                raise ApprovalRequired(
                    PendingAction(
                        approval_id=uuid.uuid4().hex[:16],
                        task_id=task_id,
                        step_id=step.step_id,
                        tool=step.tool,
                        risk=risk,
                        summary=f"{step.rationale or step.tool} ({risk.value})",
                        arguments_display=display_args,
                    )
                )
            result, target, verification = self._act_and_verify(step)
            self.sessions.mark_action()
            record = ActionRecord(
                action_id=uuid.uuid4().hex[:16],
                task_id=task_id,
                step_id=step.step_id,
                tool=step.tool,
                risk=risk,
                status="completed",
                summary=self._safe_summary(step, result),
                target_window=target,
                verification=verification,
            )
            return result, record
        except ApprovalRequired:
            raise
        except (SessionError, RegistryError, AutomationError, ActionError) as exc:
            code = getattr(exc, "code", "action_failed")
            raise ActionError(code, str(exc)) from exc

    def _act_and_verify(self, step: ActionStep) -> tuple[Any, str | None, str]:
        tool = step.tool
        args = dict(step.arguments)
        result: Any
        if tool == "windows_get_active_window":
            result = self.backend.get_active_window()
            return result, result.window_id if result else None, "active window observed"
        if tool == "windows_list_windows":
            result = self.backend.list_windows()
            return result, None, f"observed {len(result)} windows"
        if tool == "windows_get_window_info":
            result = self.backend.get_window_info(str(args.get("window_id", "")))
            return result, result.window_id, "window still exists"
        if tool == "windows_capture_screen":
            result = self.backend.capture_screen()
            return result, None, "ephemeral screen captured in memory"
        if tool == "windows_capture_window":
            window_id = str(args.get("window_id", ""))
            result = self.backend.capture_window(window_id)
            return result, window_id, "ephemeral window captured in memory"
        if tool == "windows_get_accessibility_tree":
            window_id = str(args.get("window_id", ""))
            result = self.backend.accessibility_tree(window_id)
            if any(item.password for item in result):
                # Metadata may reveal that a password field exists, never its value.
                pass
            return result, window_id, f"observed {len(result)} accessible elements"
        if tool == "windows_launch_app":
            app = self.registry.get(str(args.get("app_id", "")))
            result = self.backend.launch(app)
            launched_window = self.backend.get_window_info(result.window_id)
            return launched_window, launched_window.window_id, "application window exists"
        if tool == "windows_open_safe_path":
            path = self.registry.safe_path(str(args.get("path_id", "")))
            explorer = self.registry.get("file_explorer")
            app = type(explorer)(
                app_id=explorer.app_id,
                executable=explorer.executable,
                arguments=(str(path),),
                expected_title="",
                allow_existing_window=False,
            )
            result = self.backend.launch(app)
            return result, result.window_id, "registered safe path opened"
        window_id = self._target_window(args)
        if tool == "windows_focus_window":
            result = self.backend.focus_window(window_id)
            return result, window_id, "target window is active"
        if tool == "windows_click_element":
            element_id = str(args.get("element_id", ""))
            if not element_id:
                element = self.backend.find_element(
                    window_id,
                    control_types=(str(args.get("control_type", "Button")),),
                    name=str(args.get("name", "")),
                )
                element_id = element.element_id
            if str(args.get("action", "invoke")) == "select":
                result = self.backend.select_item(window_id, element_id, str(args.get("value", "")))
            else:
                result = self.backend.click_element(window_id, element_id)
            self.backend.get_window_info(window_id)
            return result, window_id, "element invocation completed and window re-observed"
        if tool == "windows_set_text":
            text = str(args.get("text", ""))
            element_id = str(args.get("element_id", ""))
            if not element_id:
                element = self.backend.find_element(
                    window_id, control_types=("Edit", "Document", "TextBox")
                )
                element_id = element.element_id
            observed_text = self.backend.set_text(window_id, element_id, text)
            if text not in observed_text:
                raise ActionError("verification_failed", "Typed text was not observed after action")
            return {"characters": len(text), "element_id": element_id}, window_id, "text observed"
        if tool == "windows_press_key":
            self.backend.press_key(window_id, str(args.get("key", "")))
            self.backend.get_window_info(window_id)
            return {"key": str(args.get("key", "")).upper()}, window_id, "window re-observed"
        if tool == "windows_close_window":
            self.backend.close_window(window_id)
            try:
                self.backend.get_window_info(window_id)
            except AutomationError:
                return {"closed": True}, window_id, "window no longer exists"
            raise ActionError("verification_failed", "Window still exists after close request")
        if tool == "windows_click_coordinate":
            if not bool(args.get("accessibility_unavailable")):
                raise ActionError(
                    "coordinate_fallback_forbidden",
                    "Coordinates require an explicit accessibility_unavailable result",
                )
            current = self.backend.get_active_window()
            if current is None or current.window_id != window_id:
                raise ActionError("window_not_active", "Target window is not active")
            if current.window_hash != str(args.get("window_hash", "")):
                raise ActionError("coordinate_stale", "Target window changed after screenshot")
            region_payload = args.get("target_bounds") or {}
            expected_region_hash = str(args.get("target_region_hash", ""))
            if not expected_region_hash or not region_payload:
                raise ActionError(
                    "coordinate_stale", "Coordinate target is missing its freshness proof"
                )
            try:
                target_bounds = Bounds(**region_payload)
            except (TypeError, ValueError) as exc:
                raise ActionError("coordinate_stale", "Coordinate target is invalid") from exc
            if not (
                current.bounds.left
                <= target_bounds.left
                < target_bounds.right
                <= current.bounds.right
                and current.bounds.top
                <= target_bounds.top
                < target_bounds.bottom
                <= current.bounds.bottom
            ):
                raise ActionError(
                    "coordinate_out_of_bounds", "Target region is outside the active window"
                )
            frame = self.backend.capture_screen()
            if frame.screenshot_hash != str(args.get("screenshot_hash", "")):
                try:
                    current_region_hash = self.backend.frame_region_hash(frame, target_bounds)
                except (AutomationError, TypeError, ValueError) as exc:
                    raise ActionError("coordinate_stale", "Target region changed") from exc
                if current_region_hash != expected_region_hash:
                    raise ActionError("coordinate_stale", "Target region changed")
            expected_bounds = args.get("screen_bounds") or {}
            if expected_bounds != frame.bounds.model_dump():
                raise ActionError("coordinate_stale", "Screen dimensions changed")
            x, y = int(args.get("x", -1)), int(args.get("y", -1))
            if not (
                frame.bounds.left <= x < frame.bounds.right
                and frame.bounds.top <= y < frame.bounds.bottom
            ):
                raise ActionError("coordinate_out_of_bounds", "Coordinate is outside the screen")
            if not (
                target_bounds.left <= x < target_bounds.right
                and target_bounds.top <= y < target_bounds.bottom
            ):
                raise ActionError("coordinate_out_of_bounds", "Coordinate is outside target region")
            self.backend.click_coordinate(x, y)
            self.backend.get_window_info(window_id)
            return {"clicked": True}, window_id, "target window re-observed"
        raise ActionError("tool_unavailable", f"Windows tool is unavailable: {tool}")

    def _target_window(self, args: dict[str, Any]) -> str:
        window_id = str(args.get("window_id", ""))
        if window_id:
            return window_id
        active = self.backend.get_active_window()
        if active is None:
            raise ActionError("window_not_active", "No active target window")
        return active.window_id

    @staticmethod
    def _display_arguments(step: ActionStep) -> dict[str, Any]:
        display = dict(step.arguments)
        if "text" in display:
            text = str(display["text"])
            display["text"] = text[:120]
            display["characters"] = len(text)
        return display

    @staticmethod
    def _safe_summary(step: ActionStep, result: Any) -> str:
        if step.tool == "windows_set_text":
            return f"Typed {len(str(step.arguments.get('text', '')))} characters"
        if step.tool == "windows_launch_app":
            return f"Launched registered app {step.arguments.get('app_id', '')}"
        if step.tool == "windows_list_windows":
            return f"Listed {len(result)} windows"
        return step.rationale or step.tool
