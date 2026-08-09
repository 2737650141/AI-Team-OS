from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.budget import BudgetController
from app.core.config import AppSettings, load_settings
from app.core.events import init as events_init
from app.gateway.audit import AuditLog
from app.gateway.contracts import ModelRequest, ProviderError, ProviderErrorCode
from app.gateway.model_gateway import ModelGateway
from app.gateway.router import ModelRouter, build_router
from app.gateway.structured_gen import generate_structured
from app.memory.service import MemoryService
from app.runner import _settings_with_custom_routes, build_provider
from app.windows_control.backend import AutomationError, WindowsAutomationBackend
from app.windows_control.gateway import (
    OBSERVE_TOOLS,
    RISK_BY_TOOL,
    ActionError,
    ApprovalRequired,
    WindowsActionGateway,
)
from app.windows_control.models import (
    AccessibilityElement,
    ActionRecord,
    ActionRisk,
    ActionStep,
    ComputerSnapshot,
    JarvisStatus,
    PendingAction,
    ScreenFrame,
    SessionCapability,
    SessionStatus,
    WindowsTask,
    utc_now,
)
from app.windows_control.registry import ApplicationRegistry
from app.windows_control.session import DeviceSessionManager, SessionError

SUPERVISOR_SCHEMA = {
    "intent": {"type": "str"},
    "requested_text": {"type": "str"},
    "observe_only": {"type": "bool"},
    "summary": {"type": "str"},
}

ACTION_PLAN_SCHEMA = {
    "summary": {"type": "str"},
    "actions": {"type": "list"},
}

REVIEW_SCHEMA = {
    "verdict": {"type": "str"},
    "issues": {"type": "list"},
    "summary": {"type": "str"},
}

ALLOWED_INTENTS = {
    "observe_windows",
    "open_notepad",
    "open_console",
    "open_project",
    "fixture_external_action",
}


class ComputerServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WindowsComputerService:
    """Orchestrates real-model plans while WindowsActionGateway owns every OS call."""

    def __init__(
        self,
        data_dir: Path,
        project_root: Path,
        *,
        backend: WindowsAutomationBackend | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.sessions = DeviceSessionManager()
        self.backend = backend or WindowsAutomationBackend()
        self.registry = ApplicationRegistry(project_root)
        self.gateway = WindowsActionGateway(self.sessions, self.backend, self.registry)
        self._lock = threading.RLock()
        self._jarvis_status = JarvisStatus.IDLE
        self._current_task: WindowsTask | None = None
        self._pending: dict[str, PendingAction] = {}
        self._history: list[ActionRecord] = []
        self._last_frame: ScreenFrame | None = None

    def start_session(
        self,
        capability: SessionCapability,
        *,
        ttl_minutes: int = 15,
        user_id: str = "local-user",
    ):
        with self._lock:
            self._pending.clear()
            self._jarvis_status = JarvisStatus.OBSERVING
            session = self.sessions.start(
                user_id=user_id, capability=capability, ttl_minutes=ttl_minutes
            )
            self._observe_current()
            self._jarvis_status = JarvisStatus.IDLE
            return session

    def pause(self):
        with self._lock:
            session = self.sessions.pause()
            self._jarvis_status = JarvisStatus.STOPPED
            return session

    def resume(self):
        with self._lock:
            session = self.sessions.resume()
            self._jarvis_status = JarvisStatus.IDLE
            return session

    def stop(self):
        """Mandatory emergency stop: terminate authority and cancel every queued action."""
        with self._lock:
            session = self.sessions.terminate()
            for pending in self._pending.values():
                pending.status = "cancelled"
            self._pending.clear()
            if self._current_task and self._current_task.status not in {
                "completed",
                "failed",
                "rejected",
            }:
                self._current_task.status = "stopped"
                self._current_task.error_code = "emergency_stop"
                self._current_task.result = "Control stopped by user; queued actions cancelled"
                for step in self._current_task.action_plan:
                    if step.status in {"queued", "waiting_approval"}:
                        step.status = "cancelled"
            self._last_frame = None
            self._jarvis_status = JarvisStatus.STOPPED
            return session

    def snapshot(self, *, refresh_windows: bool = True) -> ComputerSnapshot:
        with self._lock:
            session = self.sessions.current()
            windows = []
            active = None
            screen_access = bool(session and session.status is SessionStatus.ACTIVE)
            if screen_access and refresh_windows:
                try:
                    active, windows = self._observe_current()
                except (AutomationError, SessionError):
                    active, windows = None, []
            control = "off"
            if session:
                control = {
                    SessionStatus.ACTIVE: "on",
                    SessionStatus.PAUSED: "paused",
                    SessionStatus.EXPIRED: "off",
                    SessionStatus.TERMINATED: "off",
                    SessionStatus.INACTIVE: "off",
                }[session.status]
            return ComputerSnapshot(
                session=session,
                screen_access=screen_access,
                control=control,
                jarvis_status=self._jarvis_status,
                active_window=active or (session.active_window if session else None),
                windows=windows,
                current_task=self._current_task.model_copy(deep=True)
                if self._current_task
                else None,
                pending_actions=[item.model_copy(deep=True) for item in self._pending.values()],
                recent_actions=[item.model_copy(deep=True) for item in self._history[-100:]],
                safety_status={
                    "default_control": "off",
                    "general_shell": "unavailable",
                    "clipboard_read": "disabled",
                    "credential_fields": "forbidden",
                    "uac": "stop",
                    "screenshot_persistence": "ephemeral",
                    "coordinate_fallback": "accessibility_only",
                    "max_retries": 2,
                    "max_supervisor_replans": 1,
                    "application_registry": self.registry.catalog(),
                },
            )

    def capture_screen(self) -> ScreenFrame:
        with self._lock:
            self.sessions.require_active("windows_capture_screen")
            self._jarvis_status = JarvisStatus.OBSERVING
            frame, record = self.gateway.execute(
                ActionStep(
                    step_id="manual-screen",
                    tool="windows_capture_screen",
                    rationale="Refresh current screen",
                    expected_state="Current screen is visible",
                    risk=ActionRisk.OBSERVE,
                ),
                task_id=self._current_task.task_id if self._current_task else "computer-session",
            )
            if not isinstance(frame, ScreenFrame):
                raise ComputerServiceError("capture_failed", "Screen frame was unavailable")
            self._last_frame = frame
            self._append_history(record)
            self._jarvis_status = JarvisStatus.IDLE
            return frame

    def capture_window(self, window_id: str) -> ScreenFrame:
        """Capture one explicitly selected window in memory through the action gateway."""
        with self._lock:
            self.sessions.require_active("windows_capture_window")
            self._jarvis_status = JarvisStatus.OBSERVING
            frame, record = self.gateway.execute(
                ActionStep(
                    step_id="manual-window-screen",
                    tool="windows_capture_window",
                    arguments={"window_id": window_id},
                    rationale="Refresh selected window",
                    expected_state="Selected window is visible",
                    risk=ActionRisk.OBSERVE,
                ),
                task_id=self._current_task.task_id if self._current_task else "computer-session",
            )
            if not isinstance(frame, ScreenFrame):
                raise ComputerServiceError("capture_failed", "Window frame was unavailable")
            self._last_frame = frame
            self._append_history(record)
            self._jarvis_status = JarvisStatus.IDLE
            return frame

    def accessibility_tree(self, window_id: str) -> list[AccessibilityElement]:
        """Read a selected window's accessibility metadata through the action gateway."""
        with self._lock:
            self.sessions.require_active("windows_get_accessibility_tree")
            self._jarvis_status = JarvisStatus.OBSERVING
            elements, record = self.gateway.execute(
                ActionStep(
                    step_id="manual-accessibility",
                    tool="windows_get_accessibility_tree",
                    arguments={"window_id": window_id},
                    rationale="Inspect selected window accessibility metadata",
                    expected_state="Accessible elements are listed without secure values",
                    risk=ActionRisk.OBSERVE,
                ),
                task_id=self._current_task.task_id if self._current_task else "computer-session",
            )
            self._append_history(record)
            self._jarvis_status = JarvisStatus.IDLE
            return list(elements)

    def plan_task(self, goal: str) -> WindowsTask:
        with self._lock:
            session = self.sessions.require_active()
            goal = goal.strip()
            if not goal:
                raise ComputerServiceError("invalid_goal", "Goal cannot be empty")
            if len(goal) > 4000:
                raise ComputerServiceError("invalid_goal", "Goal exceeds 4000 characters")
            task_id = f"win_{uuid.uuid4().hex[:16]}"
            self._jarvis_status = JarvisStatus.PLANNING
            gateway, router, settings, provider_name = self._real_model(task_id)
            exact_text = self._extract_requested_text(goal)
            memory_applied = self._memory_requires_plan(goal)
            supervisor_telemetry: dict[str, Any] = {}
            intent = generate_structured(
                gateway,
                ModelRequest(
                    request_id=uuid.uuid4().hex[:16],
                    task_id=task_id,
                    run_id=task_id,
                    agent_id="supervisor",
                    role_type="supervisor",
                    model=router.resolve("supervisor"),
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are the Windows task supervisor. Classify only; never propose "
                                "shell commands, executable paths, credentials, UAC actions, "
                                "file saves, "
                                "or hidden reasoning. Return one JSON object. Allowed intents: "
                                "observe_windows, open_notepad, open_console, open_project, "
                                "fixture_external_action. Use fixture_external_action only for "
                                "an explicit simulated external-impact fixture button test."
                            ),
                        },
                        {"role": "user", "content": goal},
                    ],
                    response_schema=SUPERVISOR_SCHEMA,
                    temperature=0,
                    max_output_tokens=400,
                    timeout_seconds=45,
                ),
                SUPERVISOR_SCHEMA,
                settings,
                semantic_validator=lambda data: self._validate_supervisor(data, goal),
                telemetry=supervisor_telemetry,
            )
            if exact_text:
                intent["requested_text"] = exact_text
            planner_telemetry: dict[str, Any] = {}
            planner_recovered = False
            try:
                plan_payload = generate_structured(
                    gateway,
                    ModelRequest(
                    request_id=uuid.uuid4().hex[:16],
                    task_id=task_id,
                    run_id=task_id,
                    agent_id="planner",
                    role_type="planner",
                    model=router.resolve("planner"),
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Create a short Windows action plan. Return JSON only. "
                                "The model never "
                                "controls Windows directly: every action will be revalidated by "
                                "WindowsActionGateway. Never use shell, clipboard, "
                                "raw executable paths, "
                                "save, credentials, UAC, or coordinates. Allowed tools: "
                                "windows_get_active_window, windows_list_windows, "
                                "windows_launch_app, "
                                "windows_focus_window, windows_set_text, windows_open_safe_path. "
                                "For fixture_external_action only, windows_click_element is also "
                                "allowed. Use app_id notepad, ai_team_os_browser, or test_fixture; "
                                "use path_id ai_team_os_project."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "goal": goal,
                                    "supervisor": intent,
                                    "session_capability": session.capability.value,
                                    "memory_preference": (
                                        "show_action_plan_before_acting"
                                        if memory_applied
                                        else "none"
                                    ),
                                    "schema": {
                                        "summary": "string",
                                        "actions": [
                                            {
                                                "tool": "allowed tool",
                                                "arguments": {},
                                                "rationale": "user-visible reason",
                                                "expected_state": "verifiable state",
                                            }
                                        ],
                                    },
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    response_schema=ACTION_PLAN_SCHEMA,
                    temperature=0,
                    max_output_tokens=1200,
                    timeout_seconds=45,
                    ),
                    ACTION_PLAN_SCHEMA,
                    settings,
                    semantic_validator=lambda data: self._validate_plan(data, intent),
                    telemetry=planner_telemetry,
                )
            except ProviderError as exc:
                if exc.code is not ProviderErrorCode.SCHEMA_VALIDATION_FAILED:
                    raise
                # The real Planner was called and exhausted bounded structural
                # repairs. Recover only the canonical server-registered action
                # sequence for the already validated real Supervisor intent.
                # No executable, URL, path, click target, or text is invented
                # from free-form model output here.
                plan_payload = self._canonical_plan(intent)
                self._validate_plan(plan_payload, intent)
                planner_recovered = True
            steps = self._steps_from_plan(plan_payload, intent)
            task = WindowsTask(
                task_id=task_id,
                goal=goal,
                status="planned",
                provider=provider_name,
                model=router.resolve("planner"),
                planner_recovered=planner_recovered,
                action_plan=steps,
                memory_preference_applied=memory_applied,
                token_usage=self._combine_telemetry(supervisor_telemetry, planner_telemetry),
            )
            self._current_task = task
            self._pending.clear()
            self._jarvis_status = JarvisStatus.IDLE
            return task.model_copy(deep=True)

    def run_planned_task(self, task_id: str) -> WindowsTask:
        with self._lock:
            task = self._require_task(task_id)
            if task.status not in {"planned", "running", "waiting_approval"}:
                raise ComputerServiceError("invalid_task_state", f"Task cannot run: {task.status}")
            if task.status == "waiting_approval":
                return task.model_copy(deep=True)
            task.status = "running"
            self._continue_task(task)
            return task.model_copy(deep=True)

    def approve(self, approval_id: str) -> WindowsTask:
        with self._lock:
            pending = self._pending.get(approval_id)
            if pending is None or pending.status != "pending":
                raise ComputerServiceError("approval_not_found", "Pending action not found")
            task = self._require_task(pending.task_id)
            step = next(item for item in task.action_plan if item.step_id == pending.step_id)
            pending.status = "approved"
            self._jarvis_status = JarvisStatus.ACTING
            self._execute_step(task, step, approved=True)
            self._pending.pop(approval_id, None)
            task.current_step += 1
            task.status = "running"
            self._continue_task(task)
            return task.model_copy(deep=True)

    def reject(self, approval_id: str) -> WindowsTask:
        with self._lock:
            pending = self._pending.get(approval_id)
            if pending is None or pending.status != "pending":
                raise ComputerServiceError("approval_not_found", "Pending action not found")
            task = self._require_task(pending.task_id)
            pending.status = "rejected"
            step = next(item for item in task.action_plan if item.step_id == pending.step_id)
            step.status = "rejected"
            task.status = "rejected"
            task.completed_at = utc_now()
            task.result = "User rejected the pending Windows action; it was not executed"
            task.reviewer_verdict = "pass"
            self._pending.pop(approval_id, None)
            self._jarvis_status = JarvisStatus.IDLE
            return task.model_copy(deep=True)

    def _continue_task(self, task: WindowsTask) -> None:
        while task.current_step < len(task.action_plan):
            step = task.action_plan[task.current_step]
            try:
                self._jarvis_status = JarvisStatus.ACTING
                self._execute_step(task, step, approved=False)
            except ApprovalRequired as exc:
                step.status = "waiting_approval"
                task.status = "waiting_approval"
                self._pending[exc.pending.approval_id] = exc.pending
                self._jarvis_status = JarvisStatus.WAITING_APPROVAL
                return
            task.current_step += 1
        self._finish_task(task)

    def _execute_step(self, task: WindowsTask, step: ActionStep, *, approved: bool) -> None:
        transient = {
            "element_not_found",
            "window_not_active",
            "action_timeout",
            "accessibility_unavailable",
            "verification_failed",
        }
        retry_count = 0
        while True:
            try:
                result, record = self.gateway.execute(step, task_id=task.task_id, approved=approved)
                if step.tool == "windows_launch_app" and hasattr(result, "window_id"):
                    for later in task.action_plan[task.current_step + 1 :]:
                        if later.tool in {
                            "windows_focus_window",
                            "windows_set_text",
                            "windows_press_key",
                            "windows_click_element",
                        } and not later.arguments.get("window_id"):
                            later.arguments["window_id"] = result.window_id
                step.status = "completed"
                record.retry_count = retry_count
                self._append_history(record)
                return
            except ApprovalRequired:
                raise
            except ActionError as exc:
                if exc.code in transient and retry_count < 2:
                    retry_count += 1
                    continue
                if exc.code in transient and task.replan_count < 1:
                    task.replan_count += 1
                    self._append_history(
                        ActionRecord(
                            action_id=uuid.uuid4().hex[:16],
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool=step.tool,
                            risk=step.risk,
                            status="replanned",
                            summary=(
                                "Retry budget exhausted; Supervisor re-observed the validated "
                                "target and replanned the current step"
                            ),
                            error_code=exc.code,
                            retry_count=retry_count,
                        )
                    )
                    self._bounded_supervisor_replan(step)
                    retry_count = 0
                    continue
                step.status = "failed"
                task.status = "failed"
                task.completed_at = utc_now()
                task.error_code = exc.code
                task.result = str(exc)
                self._append_history(
                    ActionRecord(
                        action_id=uuid.uuid4().hex[:16],
                        task_id=task.task_id,
                        step_id=step.step_id,
                        tool=step.tool,
                        risk=step.risk,
                        status="failed",
                        summary=str(exc),
                        error_code=exc.code,
                        retry_count=retry_count,
                    )
                )
                self._jarvis_status = JarvisStatus.ERROR
                raise ComputerServiceError(exc.code, str(exc)) from exc

    def _bounded_supervisor_replan(self, step: ActionStep) -> None:
        """Re-observe only the already validated target; never broaden authority.

        The replan may discard a stale accessibility token so the gateway can
        resolve the same named/control-type element again. It never substitutes
        another window, application, path, coordinate, text, or tool.
        """
        window_id = str(step.arguments.get("window_id", ""))
        if window_id:
            try:
                self.backend.get_window_info(window_id)
            except AutomationError as exc:
                raise ComputerServiceError(exc.code, str(exc)) from exc
        if step.tool in {"windows_click_element", "windows_set_text"}:
            step.arguments.pop("element_id", None)
        step.status = "queued"

    def _finish_task(self, task: WindowsTask) -> None:
        self._jarvis_status = JarvisStatus.VERIFYING
        if any(step.status != "completed" for step in task.action_plan):
            task.status = "failed"
            task.error_code = "verification_failed"
            task.result = "Not every planned action completed"
            self._jarvis_status = JarvisStatus.ERROR
            return
        telemetry: dict[str, Any] = {}
        gateway, router, settings, _provider_name = self._real_model(task.task_id)
        data = generate_structured(
            gateway,
            ModelRequest(
                request_id=uuid.uuid4().hex[:16],
                task_id=task.task_id,
                run_id=task.task_id,
                agent_id="reviewer",
                role_type="reviewer",
                model=router.resolve("reviewer"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Review the safe action trace against the user goal. Return JSON only. "
                            "The deterministic gateway has already verified each completed action. "
                            "Reject only a concrete unmet goal; do not request hidden reasoning "
                            "or screenshots."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "goal": task.goal,
                                "plan": [step.model_dump(mode="json") for step in task.action_plan],
                                "safe_action_trace": [
                                    record.model_dump(mode="json")
                                    for record in self._history
                                    if record.task_id == task.task_id
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                response_schema=REVIEW_SCHEMA,
                temperature=0,
                max_output_tokens=500,
                timeout_seconds=45,
            ),
            REVIEW_SCHEMA,
            settings,
            semantic_validator=self._validate_review,
            telemetry=telemetry,
        )
        task.reviewer_verdict = data["verdict"]
        task.token_usage = self._combine_telemetry(task.token_usage, telemetry)
        task.completed_at = utc_now()
        if data["verdict"] == "pass":
            task.status = "completed"
            task.result = str(data.get("summary") or "Windows task completed and verified")
            self._jarvis_status = JarvisStatus.IDLE
        else:
            task.status = "failed"
            task.error_code = "review_rejected"
            task.result = str(data.get("summary") or "Reviewer rejected the completed trace")
            self._jarvis_status = JarvisStatus.ERROR

    def _real_model(self, task_id: str) -> tuple[ModelGateway, ModelRouter, AppSettings, str]:
        # A fresh gateway gives every Windows task correct event/run attribution.
        settings = _settings_with_custom_routes(load_settings(), self.data_dir)
        budget = BudgetController(30000, 2.0, max_calls=12)
        events_init(self.data_dir)
        gateway = ModelGateway(
            provider=build_provider(settings, self.data_dir),
            budget=budget,
            audit=AuditLog(self.data_dir / "audit.jsonl"),
            task_id=task_id,
            run_id=task_id,
        )
        router = build_router(
            settings,
            audit=AuditLog(self.data_dir / "audit.jsonl"),
            task_id=task_id,
        )
        provider_name = getattr(gateway._provider, "provider_name", "DeepSeek Official")
        return gateway, router, settings, provider_name

    @classmethod
    def _validate_supervisor(cls, data: dict[str, Any], goal: str = "") -> dict[str, Any]:
        intent = str(data.get("intent", ""))
        if intent not in ALLOWED_INTENTS:
            raise ValueError(f"unsupported Windows intent: {intent}")
        if not isinstance(data.get("observe_only"), bool):
            raise ValueError("observe_only must be boolean")
        if intent == "observe_windows" and not data["observe_only"]:
            raise ValueError("observe_windows must be observe-only")
        expected = cls._expected_intent(goal)
        if expected and intent != expected:
            raise ValueError(f"intent does not match the explicit user target: expected {expected}")
        return data

    @staticmethod
    def _expected_intent(goal: str) -> str | None:
        normalized = goal.lower()
        if any(marker in normalized for marker in ("记事本", "notepad")):
            return "open_notepad"
        if (
            "ai team os" in normalized
            and any(marker in normalized for marker in ("控制台", "console", "浏览器", "browser"))
        ):
            return "open_console"
        if any(marker in normalized for marker in ("外部影响", "模拟按钮", "fixture action")):
            return "fixture_external_action"
        if any(marker in normalized for marker in ("项目目录", "project directory")):
            return "open_project"
        if any(marker in normalized for marker in ("哪些窗口", "打开了哪些窗口", "list windows")):
            return "observe_windows"
        return None

    def _validate_plan(self, data: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
        actions = data.get("actions")
        if not isinstance(actions, list) or not actions or len(actions) > 8:
            raise ValueError("actions must contain 1-8 steps")
        tools = []
        for raw in actions:
            if not isinstance(raw, dict):
                raise ValueError("every action must be an object")
            tool = str(raw.get("tool", ""))
            if tool not in RISK_BY_TOOL or tool in {
                "windows_click_coordinate",
                "windows_close_window",
                "windows_press_key",
            }:
                raise ValueError(f"tool is outside this task planner surface: {tool}")
            if tool == "windows_click_element" and intent["intent"] != "fixture_external_action":
                raise ValueError("click element is limited to the external-impact fixture")
            if not isinstance(raw.get("arguments", {}), dict):
                raise ValueError("action arguments must be an object")
            tools.append(tool)
        expected_intent = str(intent["intent"])
        intent_tools = {
            "observe_windows": OBSERVE_TOOLS,
            "open_notepad": {
                "windows_launch_app",
                "windows_focus_window",
                "windows_set_text",
                "windows_get_window_info",
            },
            "open_console": {
                "windows_launch_app",
                "windows_focus_window",
                "windows_get_window_info",
            },
            "open_project": {
                "windows_open_safe_path",
                "windows_focus_window",
                "windows_get_window_info",
            },
            "fixture_external_action": {
                "windows_launch_app",
                "windows_focus_window",
                "windows_click_element",
                "windows_get_window_info",
            },
        }
        disallowed = [tool for tool in tools if tool not in intent_tools[expected_intent]]
        if disallowed:
            raise ValueError(f"actions exceed the classified intent: {disallowed}")
        if expected_intent == "observe_windows":
            if any(RISK_BY_TOOL[tool] is not ActionRisk.OBSERVE for tool in tools):
                raise ValueError("observe-only task contains a write action")
            if "windows_list_windows" not in tools:
                raise ValueError("observe_windows requires windows_list_windows")
        elif expected_intent == "open_notepad":
            launches = [raw for raw in actions if raw.get("tool") == "windows_launch_app"]
            if not launches or launches[0].get("arguments", {}).get("app_id") != "notepad":
                raise ValueError("open_notepad requires registered app_id notepad")
            if intent.get("requested_text") and "windows_set_text" not in tools:
                raise ValueError("requested text requires windows_set_text")
        elif expected_intent == "open_console":
            if not any(
                raw.get("tool") == "windows_launch_app"
                and raw.get("arguments", {}).get("app_id") == "ai_team_os_browser"
                for raw in actions
            ):
                raise ValueError("open_console requires registered AI Team OS browser")
        elif expected_intent == "open_project":
            if not any(
                raw.get("tool") == "windows_open_safe_path"
                and raw.get("arguments", {}).get("path_id") == "ai_team_os_project"
                for raw in actions
            ):
                raise ValueError("open_project requires registered safe path")
        elif expected_intent == "fixture_external_action":
            if not any(
                raw.get("tool") == "windows_launch_app"
                and raw.get("arguments", {}).get("app_id") == "test_fixture"
                for raw in actions
            ):
                raise ValueError("fixture action requires registered test_fixture")
            if not any(raw.get("tool") == "windows_click_element" for raw in actions):
                raise ValueError("fixture action requires windows_click_element")
        return data

    @staticmethod
    def _validate_review(data: dict[str, Any]) -> dict[str, Any]:
        if data.get("verdict") not in {"pass", "reject"}:
            raise ValueError("review verdict must be pass or reject")
        if not isinstance(data.get("issues"), list):
            raise ValueError("review issues must be a list")
        return data

    @staticmethod
    def _canonical_plan(intent: dict[str, Any]) -> dict[str, Any]:
        name = str(intent["intent"])
        action_map: dict[str, list[dict[str, Any]]] = {
            "observe_windows": [
                {
                    "tool": "windows_list_windows",
                    "arguments": {},
                    "rationale": "List visible application windows without modifying them",
                    "expected_state": "Visible windows are returned",
                }
            ],
            "open_notepad": [
                {
                    "tool": "windows_launch_app",
                    "arguments": {"app_id": "notepad"},
                    "rationale": "Open the server-registered Notepad application",
                    "expected_state": "A Notepad window exists",
                }
            ],
            "open_console": [
                {
                    "tool": "windows_launch_app",
                    "arguments": {"app_id": "ai_team_os_browser"},
                    "rationale": "Open the registered local AI Team OS console",
                    "expected_state": "The local console browser window exists",
                }
            ],
            "open_project": [
                {
                    "tool": "windows_open_safe_path",
                    "arguments": {"path_id": "ai_team_os_project"},
                    "rationale": "Open the registered AI Team OS project path",
                    "expected_state": "File Explorer shows the registered project path",
                }
            ],
            "fixture_external_action": [
                {
                    "tool": "windows_launch_app",
                    "arguments": {"app_id": "test_fixture"},
                    "rationale": "Open the registered external-impact test fixture",
                    "expected_state": "The fixture window exists",
                },
                {
                    "tool": "windows_click_element",
                    "arguments": {
                        "name": "Fixture Action",
                        "control_type": "Button",
                        "action": "invoke",
                    },
                    "rationale": "Invoke the simulated external-impact button",
                    "expected_state": "The fixture status changes to Button clicked",
                },
            ],
        }
        actions = [dict(item) for item in action_map[name]]
        if name == "open_notepad" and intent.get("requested_text"):
            actions.append(
                {
                    "tool": "windows_set_text",
                    "arguments": {"text": str(intent["requested_text"])},
                    "rationale": "Enter the exact user-requested ordinary text",
                    "expected_state": "The requested text is observed in Notepad",
                }
            )
        return {"summary": f"Canonical safe plan for {name}", "actions": actions}

    @staticmethod
    def _steps_from_plan(data: dict[str, Any], intent: dict[str, Any]) -> list[ActionStep]:
        result = []
        requested_text = str(intent.get("requested_text", ""))
        for index, raw in enumerate(data["actions"], 1):
            tool = str(raw["tool"])
            arguments = dict(raw.get("arguments") or {})
            if tool == "windows_set_text":
                arguments["text"] = requested_text
            if (
                tool == "windows_click_element"
                and intent.get("intent") == "fixture_external_action"
            ):
                arguments = {
                    "name": "Fixture Action",
                    "control_type": "Button",
                    "action": "invoke",
                }
            result.append(
                ActionStep(
                    step_id=f"step-{index}",
                    tool=tool,
                    arguments=arguments,
                    rationale=str(raw.get("rationale", ""))[:500],
                    expected_state=str(raw.get("expected_state", ""))[:500],
                    risk=RISK_BY_TOOL[tool],
                )
            )
        return result

    @staticmethod
    def _extract_requested_text(goal: str) -> str:
        patterns = [
            r"[“\"]([^”\"]{1,2000})[”\"]",
            r"输入[:：]\s*([^\r\n]{1,2000})",
            r"write\s+[:\"]?([^\r\n\"]{1,2000})",
        ]
        for pattern in patterns:
            match = re.search(pattern, goal, re.I)
            if match:
                return match.group(1).strip()
        return ""

    def _memory_requires_plan(self, goal: str) -> bool:
        try:
            memories = MemoryService.from_data_dir(self.data_dir).retrieve(
                query=f"{goal} 控制电脑 操作计划",
                project_id="windows-control",
                role="supervisor",
            )
        except Exception:
            return False
        return any(
            ("计划" in memory.value or "plan" in memory.value.lower())
            and memory.memory_type == "procedural_preference"
            for memory in memories
        )

    def _observe_current(self):
        if self.backend.is_locked():
            try:
                self.sessions.pause()
            except SessionError:
                pass
            raise ComputerServiceError(
                "windows_session_locked", "Windows is locked; control paused"
            )
        active = self.backend.get_active_window()
        windows = self.backend.list_windows()
        self.sessions.set_active_window(active)
        return active, windows

    def _append_history(self, record: ActionRecord) -> None:
        self._history.append(record)
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def _require_task(self, task_id: str) -> WindowsTask:
        if self._current_task is None or self._current_task.task_id != task_id:
            raise ComputerServiceError("task_not_found", "Windows task not found")
        self.sessions.require_active()
        return self._current_task

    @staticmethod
    def _combine_telemetry(*items: dict[str, Any]) -> dict[str, int | float | None]:
        numeric = (int, float)
        keys = ("input_tokens", "output_tokens", "cached_tokens", "total_tokens", "latency_ms")
        result: dict[str, int | float | None] = {}
        for key in keys:
            values = [item.get(key) for item in items if isinstance(item.get(key), numeric)]
            result[key] = sum(float(value) for value in values if value is not None) or None
        return result
