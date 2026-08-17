from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mss")  # win32-only：CI(Linux) 上收集期提前跳过

from app.windows_control.backend import AutomationError, WindowsAutomationBackend
from app.windows_control.gateway import ActionError, ApprovalRequired, WindowsActionGateway
from app.windows_control.models import (
    AccessibilityElement,
    ActionRisk,
    ActionStep,
    Bounds,
    ScreenFrame,
    SessionCapability,
    SessionStatus,
    WindowInfo,
    WindowsTask,
)
from app.windows_control.registry import ApplicationRegistry, RegistryError
from app.windows_control.service import WindowsComputerService
from app.windows_control.session import DeviceSessionManager, SessionError

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows action layer is Windows-only"
)


def window(*, active: bool = True, suffix: str = "a") -> WindowInfo:
    return WindowInfo(
        window_id=f"hwnd:{suffix}",
        title="Fixture",
        process_id=10,
        app_name="Fixture",
        bounds=Bounds(left=0, top=0, right=800, bottom=600),
        is_active=active,
        window_hash=f"window-{suffix}",
    )


class FakeBackend:
    def __init__(self) -> None:
        self.active = window()
        self.locked = False
        self.elevation = False
        self.clicked = 0
        self.text = ""
        self.frame = ScreenFrame(
            screenshot_hash="screen-a",
            bounds=Bounds(left=0, top=0, right=800, bottom=600),
            image_base64=base64.b64encode(b"fixture-png").decode(),
        )
        self.element = AccessibilityElement(
            element_id="uia:text",
            window_id=self.active.window_id,
            name="Text",
            control_type="Edit",
            bounds=Bounds(left=10, top=10, right=300, bottom=40),
        )

    def is_locked(self) -> bool:
        return self.locked

    def has_elevation_prompt(self) -> bool:
        return self.elevation

    def get_active_window(self):
        return self.active

    def list_windows(self):
        return [self.active]

    def get_window_info(self, window_id: str):
        if window_id != self.active.window_id:
            raise AutomationError("window_changed", "window changed")
        return self.active

    def capture_screen(self):
        return self.frame

    def capture_window(self, _window_id: str):
        return self.frame

    def accessibility_tree(self, _window_id: str):
        return [self.element]

    def launch(self, _app):
        return self.active

    def focus_window(self, _window_id: str):
        return self.active

    def find_element(self, _window_id: str, **_kwargs):
        return self.element

    def click_element(self, _window_id: str, _element_id: str):
        if self.element.password:
            raise AutomationError("credential_field_forbidden", "password blocked")
        self.clicked += 1
        return self.element

    def set_text(self, _window_id: str, _element_id: str, text: str):
        if self.element.password:
            raise AutomationError("credential_field_forbidden", "password blocked")
        self.text = text
        return text

    def press_key(self, _window_id: str, _key: str):
        return None

    def close_window(self, _window_id: str):
        self.active = window(suffix="b")

    def click_coordinate(self, _x: int, _y: int):
        self.clicked += 1

    def frame_region_hash(self, _frame: ScreenFrame, _region: Bounds) -> str:
        return "region-a"


@pytest.fixture
def gateway(tmp_path: Path):
    sessions = DeviceSessionManager()
    backend = FakeBackend()
    registry = ApplicationRegistry(tmp_path)
    return WindowsActionGateway(sessions, backend, registry), sessions, backend


def observe_step(tool: str = "windows_get_active_window") -> ActionStep:
    return ActionStep(step_id="s1", tool=tool, risk=ActionRisk.OBSERVE)


def test_backend_selects_list_item_without_calling_broken_invoke(monkeypatch) -> None:
    backend = WindowsAutomationBackend()
    element = AccessibilityElement(
        element_id="uia:list-two",
        window_id="hwnd:a",
        name="Two",
        control_type="ListItem",
    )
    calls: list[str] = []
    wrapper = SimpleNamespace(
        select=lambda: calls.append("select"),
        invoke=lambda: calls.append("invoke"),
    )
    monkeypatch.setattr(backend, "_resolve_element", lambda *_args: (wrapper, element))

    assert backend.click_element("hwnd:a", element.element_id) == element
    assert calls == ["select"]


def test_computer_control_defaults_off_and_inactive_session_blocks(gateway) -> None:
    action_gateway, sessions, _backend = gateway
    assert sessions.current() is None
    with pytest.raises(ActionError, match="not active") as exc:
        action_gateway.execute(observe_step(), task_id="task")
    assert exc.value.code == "inactive_session"


def test_observe_only_lists_windows_but_blocks_write(gateway) -> None:
    action_gateway, sessions, _backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.OBSERVE_ONLY)
    result, _record = action_gateway.execute(
        observe_step("windows_list_windows"), task_id="task"
    )
    assert len(result) == 1
    with pytest.raises(ActionError) as exc:
        action_gateway.execute(
            ActionStep(
                step_id="s2",
                tool="windows_set_text",
                arguments={"text": "blocked"},
                risk=ActionRisk.MEDIUM,
            ),
            task_id="task",
        )
    assert exc.value.code == "permission_denied"


def test_medium_action_requires_approval_and_rejection_never_executes(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    step = ActionStep(
        step_id="s1",
        tool="windows_set_text",
        arguments={"window_id": backend.active.window_id, "text": "hello"},
        risk=ActionRisk.MEDIUM,
    )
    with pytest.raises(ApprovalRequired):
        action_gateway.execute(step, task_id="task")
    assert backend.text == ""


def test_password_field_is_forbidden_even_after_approval(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    backend.element.password = True
    with pytest.raises(ActionError) as exc:
        action_gateway.execute(
            ActionStep(
                step_id="s1",
                tool="windows_set_text",
                arguments={"window_id": backend.active.window_id, "text": "secret"},
                risk=ActionRisk.MEDIUM,
            ),
            task_id="task",
            approved=True,
        )
    assert exc.value.code == "credential_field_forbidden"
    assert backend.text == ""


def test_uac_stops_session_without_acting(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    backend.elevation = True
    with pytest.raises(ActionError) as exc:
        action_gateway.execute(observe_step(), task_id="task")
    assert exc.value.code == "ELEVATION_REQUIRED"
    assert sessions.current().status is SessionStatus.TERMINATED  # type: ignore[union-attr]


def test_locked_windows_session_pauses_without_acting(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    backend.locked = True
    with pytest.raises(ActionError) as exc:
        action_gateway.execute(observe_step(), task_id="task")
    assert exc.value.code == "windows_session_locked"
    assert sessions.current().status is SessionStatus.PAUSED  # type: ignore[union-attr]


def test_stale_coordinate_is_rejected(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    step = ActionStep(
        step_id="s1",
        tool="windows_click_coordinate",
        risk=ActionRisk.HIGH,
        arguments={
            "window_id": backend.active.window_id,
            "accessibility_unavailable": True,
            "window_hash": "stale-window",
            "screenshot_hash": "screen-a",
            "screen_bounds": backend.frame.bounds.model_dump(),
            "x": 20,
            "y": 20,
        },
    )
    with pytest.raises(ActionError) as exc:
        action_gateway.execute(step, task_id="task", approved=True)
    assert exc.value.code == "coordinate_stale"
    assert backend.clicked == 0


def test_coordinate_click_must_remain_inside_fresh_target_region(gateway) -> None:
    action_gateway, sessions, backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    step = ActionStep(
        step_id="s1",
        tool="windows_click_coordinate",
        risk=ActionRisk.HIGH,
        arguments={
            "window_id": backend.active.window_id,
            "accessibility_unavailable": True,
            "window_hash": backend.active.window_hash,
            "screenshot_hash": backend.frame.screenshot_hash,
            "screen_bounds": backend.frame.bounds.model_dump(),
            "target_bounds": Bounds(left=10, top=10, right=60, bottom=60).model_dump(),
            "target_region_hash": "region-a",
            "x": 700,
            "y": 500,
        },
    )

    with pytest.raises(ActionError) as exc:
        action_gateway.execute(step, task_id="task", approved=True)

    assert exc.value.code == "coordinate_out_of_bounds"
    assert backend.clicked == 0


def test_expired_and_stopped_sessions_block_actions(gateway) -> None:
    action_gateway, sessions, _backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.OBSERVE_ONLY)
    sessions.force_expire_for_test()
    with pytest.raises(ActionError) as expired:
        action_gateway.execute(observe_step(), task_id="task")
    assert expired.value.code == "expired_session"

    sessions.start(user_id="u", capability=SessionCapability.OBSERVE_ONLY)
    sessions.terminate()
    with pytest.raises(ActionError) as stopped:
        action_gateway.execute(observe_step(), task_id="task")
    assert stopped.value.code == "action_after_stop"


def test_registry_rejects_absolute_unknown_shell_and_outside_path(tmp_path: Path) -> None:
    registry = ApplicationRegistry(tmp_path)
    for app_id, code in (
        (r"C:\unknown.exe", "absolute_executable_rejected"),
        ("unknown", "unknown_application"),
        ("powershell", "forbidden_application"),
    ):
        with pytest.raises(RegistryError) as exc:
            registry.get(app_id)
        assert exc.value.code == code
    with pytest.raises(RegistryError) as path_error:
        registry.safe_path(r"C:\outside")
    assert path_error.value.code == "path_outside_allowlist"


def test_only_declared_single_instance_app_may_reuse_existing_window() -> None:
    project_root = Path(__file__).resolve().parents[1]
    registry = ApplicationRegistry(project_root)

    assert registry.get("test_fixture").allow_existing_window is False
    if "ai_team_os_browser" in registry.catalog()["applications"]:
        assert registry.get("ai_team_os_browser").allow_existing_window is True


def test_screenshot_is_ephemeral_and_not_written(gateway, tmp_path: Path) -> None:
    action_gateway, sessions, _backend = gateway
    sessions.start(user_id="u", capability=SessionCapability.OBSERVE_ONLY)
    frame, _record = action_gateway.execute(
        observe_step("windows_capture_screen"), task_id="task"
    )
    assert frame.ephemeral is True
    assert list(tmp_path.rglob("*.png")) == []


def test_session_manager_pause_resume_and_stop() -> None:
    sessions = DeviceSessionManager()
    sessions.start(user_id="u", capability=SessionCapability.LOW_RISK_CONTROL)
    assert sessions.pause().status is SessionStatus.PAUSED
    with pytest.raises(SessionError) as paused:
        sessions.require_active()
    assert paused.value.code == "paused_session"
    assert sessions.resume().status is SessionStatus.ACTIVE
    assert sessions.terminate().status is SessionStatus.TERMINATED  # type: ignore[union-attr]


def test_requested_text_preserves_terminal_chinese_punctuation() -> None:
    goal = "打开记事本，在里面输入：“这是 AI Team OS 的第一次真实 Windows 控制测试。”不要保存文件。"
    assert WindowsComputerService._extract_requested_text(goal) == (
        "这是 AI Team OS 的第一次真实 Windows 控制测试。"
    )
    assert (
        WindowsComputerService._expected_intent("打开浏览器访问 AI Team OS 控制台。")
        == "open_console"
    )
    with pytest.raises(ValueError, match="expected open_console"):
        WindowsComputerService._validate_supervisor(
            {
                "intent": "fixture_external_action",
                "requested_text": "",
                "observe_only": False,
                "summary": "wrong",
            },
            "打开浏览器访问 AI Team OS 控制台。",
        )


def test_external_impact_fixture_is_the_only_click_planner_surface(tmp_path: Path) -> None:
    service = WindowsComputerService(tmp_path / "data", tmp_path, backend=FakeBackend())
    fixture_intent = {
        "intent": "fixture_external_action",
        "requested_text": "",
        "observe_only": False,
        "summary": "fixture",
    }
    valid = {
        "summary": "test approval",
        "actions": [
            {"tool": "windows_launch_app", "arguments": {"app_id": "test_fixture"}},
            {
                "tool": "windows_click_element",
                "arguments": {"name": "Fixture Action"},
            },
        ],
    }
    assert service._validate_plan(valid, fixture_intent) == valid
    canonical_console = service._canonical_plan(
        {
            "intent": "open_console",
            "requested_text": "",
            "observe_only": False,
            "summary": "console",
        }
    )
    assert canonical_console["actions"] == [
        {
            "tool": "windows_launch_app",
            "arguments": {"app_id": "ai_team_os_browser"},
            "rationale": "Open the registered local AI Team OS console",
            "expected_state": "The local console browser window exists",
        }
    ]

    with pytest.raises(ValueError, match="limited"):
        service._validate_plan(
            {
                "summary": "unsafe click",
                "actions": [
                    {"tool": "windows_click_element", "arguments": {"name": "Submit"}}
                ],
            },
            {
                "intent": "open_notepad",
                "requested_text": "",
                "observe_only": False,
                "summary": "notepad",
            },
        )

    with pytest.raises(ValueError, match="exceed"):
        service._validate_plan(
            {
                "summary": "extra action",
                "actions": [
                    {
                        "tool": "windows_launch_app",
                        "arguments": {"app_id": "ai_team_os_browser"},
                    },
                    {
                        "tool": "windows_open_safe_path",
                        "arguments": {"path_id": "ai_team_os_project"},
                    },
                ],
            },
            {
                "intent": "open_console",
                "requested_text": "",
                "observe_only": False,
                "summary": "console",
            },
        )


def test_computer_api_session_lifecycle_and_ephemeral_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import server

    service = WindowsComputerService(tmp_path / "data", tmp_path, backend=FakeBackend())
    monkeypatch.setattr(server, "_computer_cache", service)
    with TestClient(server.app) as client:
        assert client.get("/computer").json()["control"] == "off"
        started = client.post(
            "/computer/session/start", json={"capability": "observe_only", "ttl_minutes": 5}
        )
        assert started.status_code == 200
        assert started.json()["screen_access"] is True
        frame = client.get("/computer/screen")
        assert frame.status_code == 200
        assert frame.json()["ephemeral"] is True
        window_frame = client.get("/computer/windows/hwnd:a/screen")
        assert window_frame.status_code == 200
        assert window_frame.json()["ephemeral"] is True
        tree = client.get("/computer/windows/hwnd:a/accessibility")
        assert tree.status_code == 200
        assert tree.json()["elements"][0]["name"] == "Text"
        assert client.post("/computer/session/pause").json()["control"] == "paused"
        assert client.post("/computer/session/resume").json()["control"] == "on"
        stopped = client.post("/computer/session/stop").json()
        assert stopped["control"] == "off"
        assert stopped["screen_access"] is False


def test_retry_budget_triggers_one_bounded_supervisor_replan(tmp_path: Path) -> None:
    class RecoveringBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def focus_window(self, _window_id: str):
            self.calls += 1
            if self.calls <= 3:
                raise AutomationError("window_not_active", "transient focus failure")
            return self.active

    backend = RecoveringBackend()
    service = WindowsComputerService(tmp_path / "data", tmp_path, backend=backend)
    service.sessions.start(
        user_id="u", capability=SessionCapability.LOW_RISK_CONTROL
    )
    step = ActionStep(
        step_id="step-1",
        tool="windows_focus_window",
        arguments={"window_id": backend.active.window_id},
        risk=ActionRisk.LOW,
    )
    task = WindowsTask(task_id="task", goal="focus", action_plan=[step])

    service._execute_step(task, step, approved=False)

    assert task.replan_count == 1
    assert backend.calls == 4
    assert step.status == "completed"
    assert any(item.status == "replanned" for item in service._history)
