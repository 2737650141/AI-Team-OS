from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    PAUSED = "paused"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class SessionCapability(str, Enum):
    OBSERVE_ONLY = "observe_only"
    LOW_RISK_CONTROL = "low_risk_control"
    ASK_EVERY_ACTION = "ask_every_action"


class ActionRisk(str, Enum):
    OBSERVE = "observe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FORBIDDEN = "forbidden"


class JarvisStatus(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    ACTING = "acting"
    VERIFYING = "verifying"
    STOPPED = "stopped"
    ERROR = "error"


class Bounds(BaseModel):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class WindowInfo(BaseModel):
    window_id: str
    title: str
    process_id: int | None = None
    app_name: str = ""
    bounds: Bounds
    is_active: bool = False
    window_hash: str


class AccessibilityElement(BaseModel):
    element_id: str
    window_id: str
    name: str = ""
    control_type: str = ""
    automation_id: str = ""
    enabled: bool = True
    password: bool = False
    bounds: Bounds | None = None


class ScreenFrame(BaseModel):
    captured_at: str = Field(default_factory=utc_now)
    screenshot_hash: str
    bounds: Bounds
    image_base64: str = Field(repr=False)
    mime_type: str = "image/png"
    ephemeral: bool = True


class DeviceSession(BaseModel):
    session_id: str
    user_id: str
    started_at: str
    expires_at: str
    status: SessionStatus
    allowed_capabilities: list[str]
    capability: SessionCapability
    active_window: WindowInfo | None = None
    action_count: int = 0
    last_action_at: str | None = None


class ActionStep(BaseModel):
    step_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    expected_state: str = ""
    risk: ActionRisk
    status: str = "queued"


class WindowsTask(BaseModel):
    task_id: str
    goal: str
    status: str = "planning"
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None
    model_mode: str = "real"
    provider: str = ""
    model: str = ""
    real_call: bool = True
    planner_recovered: bool = False
    replan_count: int = 0
    action_plan: list[ActionStep] = Field(default_factory=list)
    current_step: int = 0
    result: str = ""
    error_code: str | None = None
    memory_preference_applied: bool = False
    reviewer_verdict: str | None = None
    token_usage: dict[str, int | float | None] = Field(default_factory=dict)


class PendingAction(BaseModel):
    approval_id: str
    task_id: str
    step_id: str
    tool: str
    risk: ActionRisk
    summary: str
    arguments_display: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    status: str = "pending"


class ActionRecord(BaseModel):
    action_id: str
    task_id: str | None = None
    step_id: str | None = None
    timestamp: str = Field(default_factory=utc_now)
    tool: str
    risk: ActionRisk
    status: str
    summary: str
    target_window: str | None = None
    verification: str | None = None
    error_code: str | None = None
    retry_count: int = 0


class ComputerSnapshot(BaseModel):
    session: DeviceSession | None = None
    screen_access: bool = False
    control: str = "off"
    jarvis_status: JarvisStatus = JarvisStatus.IDLE
    active_window: WindowInfo | None = None
    windows: list[WindowInfo] = Field(default_factory=list)
    current_task: WindowsTask | None = None
    pending_actions: list[PendingAction] = Field(default_factory=list)
    recent_actions: list[ActionRecord] = Field(default_factory=list)
    safety_status: dict[str, Any] = Field(default_factory=dict)
    vision_status: dict[str, Any] = Field(default_factory=dict)
